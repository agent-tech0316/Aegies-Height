import asyncio
import importlib
import unittest

import agentech as agt


class AgentechSdkTests(unittest.TestCase):
    def test_dog_initialization(self):
        dog = agt.Dog(mode="dry_run")
        self.addCleanup(dog.close)
        self.assertEqual(dog.mode, "dry_run")
        self.assertIsNotNone(dog.agt)

    def test_no_key_defaults_to_dry_run(self):
        dog = agt.Dog()
        self.addCleanup(dog.close)
        self.assertEqual(dog.mode, "dry_run")
        status = dog.agt.get_status()
        self.assertEqual(status.status, "ok")
        self.assertEqual(status.result["mode"], "dry_run")

    def test_windows_import_and_simulation_without_ff_sdk(self):
        module = importlib.import_module("agentech")
        dog = module.Dog(mode="simulation")
        self.addCleanup(dog.close)
        result = dog.agt.get_status()
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.result["mode"], "simulation")

    def test_move_forward_meter_unit_converts_to_duration(self):
        dog = agt.Dog(mode="dry_run")
        self.addCleanup(dog.close)
        dog.agt.set_forward_speed(0.25)
        result = dog.agt.move_forward(1, unit="m")
        self.assertEqual(result.action, "move_forward")
        self.assertAlmostEqual(result.result["duration_s"], 4.0)
        self.assertAlmostEqual(result.result["distance_m"], 1.0)

    def test_invalid_unit_raises(self):
        dog = agt.Dog(mode="dry_run")
        self.addCleanup(dog.close)
        with self.assertRaises(ValueError):
            dog.agt.move_forward(1, unit="cm")

    def test_overspeed_raises(self):
        dog = agt.Dog(mode="dry_run")
        self.addCleanup(dog.close)
        with self.assertRaises(ValueError):
            dog.agt.set_forward_speed(agt.SAFE_MAX_FORWARD_SPEED_MPS + 0.01)

    def test_emergency_stop_blocks_move_forward(self):
        dog = agt.Dog(mode="dry_run")
        self.addCleanup(dog.close)
        stop_result = dog.agt.emergency_stop(reason="test")
        self.assertEqual(stop_result.status, "ok")
        with self.assertRaises(agt.SafetyError):
            dog.agt.move_forward(1)

    def test_async_dog(self):
        async def run():
            dog = agt.AsyncDog(mode="dry_run")
            try:
                result = await dog.agt.stand()
                self.assertEqual(result.status, "ok")
            finally:
                await dog.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
