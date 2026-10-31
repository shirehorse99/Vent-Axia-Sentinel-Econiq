"""Offline math/window/persistence tests; no HA imports or network."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import math
from pathlib import Path
import statistics
import unittest

spec = importlib.util.spec_from_file_location('recovery_pure', Path(__file__).resolve().parents[1] / 'custom_components/ventaxia_econiq_readonly/recovery.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)
BASE = dict(outdoor_temperature=0, supply_temperature=15, indoor_temperature=20,
            supply_rpm=1000, extract_rpm=900)


class RecoveryTests(unittest.TestCase):
    def test_heating_and_cooling_same_formula(self):
        current = r.RecoveryStatistics.current(BASE, True)
        self.assertEqual(current['recovery_ratio'], 75)
        self.assertEqual(current['temperature_lift'], 15)
        self.assertEqual(current['available_temperature_difference'], 20)
        self.assertEqual(current['remaining_temperature_difference'], 5)
        cooling = BASE | dict(outdoor_temperature=30, supply_temperature=24, indoor_temperature=22)
        self.assertEqual(r.RecoveryStatistics.current(cooling, True)['recovery_ratio'], 75)

    def test_small_delta_only_suppresses_ratio(self):
        for delta in (0, 2.99, -2.99):
            value = r.RecoveryStatistics.current(BASE | {'indoor_temperature':delta}, True)
            self.assertIsNone(value['recovery_ratio'])
            self.assertEqual(value['temperature_lift'],15)
            self.assertIn('below 3 K',value['recovery_status'])
        self.assertIsNotNone(r.RecoveryStatistics.current(BASE | {'indoor_temperature':3},True)['recovery_ratio'])

    def test_missing_invalid_zero_fans_and_disconnect(self):
        for invalid in (None, True, False, float('nan'), float('inf'), '20', 10**1000):
            value=r.RecoveryStatistics.current(BASE | {'outdoor_temperature':invalid},True)
            self.assertTrue(all(v is None for k,v in value.items() if k!='recovery_status'))
        for key in ('supply_rpm','extract_rpm'):
            for invalid in (0,-1,None):
                self.assertIsNone(r.RecoveryStatistics.current(BASE | {key:invalid},True)['recovery_ratio'])
        self.assertIsNone(r.RecoveryStatistics.current({},True)['recovery_ratio'])
        self.assertEqual(r.RecoveryStatistics.current(BASE,False)['recovery_status'],'Disconnected')

    def test_outliers_are_not_clipped(self):
        for supply,expected in [(25,125),(-5,-25)]:
            value=r.RecoveryStatistics.current(BASE | {'supply_temperature':supply},True)
            self.assertEqual(value['recovery_ratio'],expected)
            self.assertIn('Outside',value['recovery_status'])

    def test_fixed_minute_sampling_gap_and_coverage(self):
        obj=r.RecoveryStatistics()
        obj.sample(NOW,BASE,True)
        obj.sample(NOW+timedelta(seconds=20),BASE | {'supply_temperature':20},True)
        obj.sample(NOW+timedelta(minutes=1),BASE,False)
        obj.sample(NOW+timedelta(minutes=3),BASE,True)
        stats=obj.stats(NOW+timedelta(minutes=3))
        self.assertEqual(stats['recovery_samples_24h'],2)
        self.assertEqual(len(obj.snapshot()['samples']),3)
        self.assertEqual(stats['recovery_mean_24h'],75)
        self.assertAlmostEqual(stats['recovery_coverage_1h'],2/60*100)
        self.assertAlmostEqual(stats['recovery_coverage_24h'],2/1440*100)
        self.assertEqual(stats['recovery_oldest_sample'],NOW)
        self.assertEqual(stats['recovery_newest_sample'],NOW+timedelta(minutes=3))

    def test_window_left_exclusive_and_retention(self):
        obj=r.RecoveryStatistics()
        for index in range(1441): obj.sample(NOW+timedelta(minutes=index),BASE,True)
        stats=obj.stats(NOW+timedelta(days=1))
        self.assertEqual(stats['recovery_samples_24h'],1440)
        self.assertEqual(stats['recovery_oldest_sample'],NOW+timedelta(minutes=1))
        self.assertEqual(stats['recovery_coverage_1h'],100)
        self.assertEqual(stats['recovery_coverage_24h'],100)
        self.assertEqual(obj.stats(NOW+timedelta(days=3))['recovery_samples_24h'],0)

    def test_distribution_and_percentile_minimum(self):
        obj=r.RecoveryStatistics()
        for index in range(19): obj.sample(NOW+timedelta(minutes=index),BASE | {'supply_temperature':index/5},True)
        self.assertIsNone(obj.stats(NOW+timedelta(minutes=18))['recovery_p10_24h'])
        obj.sample(NOW+timedelta(minutes=19),BASE | {'supply_temperature':19/5},True)
        stats=obj.stats(NOW+timedelta(minutes=19))
        self.assertAlmostEqual(stats['recovery_mean_24h'],9.5)
        self.assertAlmostEqual(stats['recovery_median_24h'],9.5)
        self.assertAlmostEqual(stats['recovery_sd_24h'],statistics.stdev(range(20)))
        self.assertAlmostEqual(stats['recovery_p10_24h'],1.9)
        self.assertAlmostEqual(stats['recovery_p90_24h'],17.1)
        self.assertEqual(stats['recovery_minimum_24h'],0)
        self.assertEqual(stats['recovery_maximum_24h'],19)
        self.assertAlmostEqual(stats['lift_mean_24h'],1.9)

    def test_empty_and_single_sample(self):
        obj=r.RecoveryStatistics()
        self.assertIsNone(obj.stats(NOW)['recovery_mean_24h'])
        obj.sample(NOW,BASE,True)
        self.assertIsNone(obj.stats(NOW)['recovery_sd_24h'])

    def test_instances_independent_and_json_roundtrip(self):
        a,b=r.RecoveryStatistics(),r.RecoveryStatistics()
        a.sample(NOW,BASE,True)
        self.assertEqual(b.stats(NOW)['recovery_samples_24h'],0)
        b.restore(json.loads(json.dumps(a.snapshot(),allow_nan=False)),NOW)
        self.assertEqual(a.stats(NOW),b.stats(NOW))
        b.sample(NOW+timedelta(minutes=1),BASE,True)
        self.assertEqual(a.stats(NOW)['recovery_samples_24h'],1)

    def test_restore_rejects_bad_future_duplicate_and_oversized_data(self):
        obj=r.RecoveryStatistics()
        good={'at':NOW.isoformat(),'ratio':75,'lift':15}
        rows=[good,good,good | {'at':(NOW+timedelta(minutes=1)).isoformat()},
              good | {'at':(NOW-timedelta(days=1)).isoformat()},good | {'at':'bad'},
              good | {'at':NOW.replace(tzinfo=None).isoformat()},
              good | {'ratio':True},good | {'ratio':float('nan')},
              good | {'lift':float('inf')},good | {'ratio':75,'lift':None},
              good | {'extra':1},None]
        obj.restore({'samples':rows},NOW)
        self.assertEqual(obj.stats(NOW)['recovery_samples_24h'],1)
        obj.restore({'samples':[good]*1441},NOW)
        self.assertEqual(obj.stats(NOW)['recovery_samples_24h'],0)
        for data in (None,{},[],{'samples':'bad'}):
            obj.restore(data,NOW)
            self.assertEqual(obj.stats(NOW)['recovery_samples_24h'],0)

    def test_restore_invalid_marker_and_unclipped_values(self):
        obj=r.RecoveryStatistics()
        obj.restore({'samples':[
            {'at':NOW.isoformat(),'ratio':None,'lift':None},
            {'at':(NOW-timedelta(minutes=1)).isoformat(),'ratio':125,'lift':25}]},NOW)
        self.assertEqual(obj.stats(NOW)['recovery_mean_24h'],125)
        obj.sample(NOW,BASE,True)
        self.assertEqual(obj.stats(NOW)['recovery_samples_24h'],1)

    def test_timezones_are_aware_and_normalized(self):
        obj=r.RecoveryStatistics()
        with self.assertRaises(ValueError):obj.sample(NOW.replace(tzinfo=None),BASE,True)
        obj.sample(NOW.astimezone(timezone(timedelta(hours=2))),BASE,True)
        self.assertEqual(obj.stats(NOW)['recovery_oldest_sample'],NOW)


if __name__=='__main__':unittest.main()
