import os
import sys
import types
import unittest


class FakeMotion:
    def __init__(self, calls):
        self.calls = calls

    async def cmd_vel(self, linear=0.0, angular=0.0):
        self.calls.append(("cmd_vel", linear, angular))

    async def stop(self):
        self.calls.append(("stop",))

    async def stand(self):
        self.calls.append(("stand",))

    async def attitude_control(self, **kwargs):
        self.calls.append(("attitude_control", kwargs))


class FakeSession:
    def __init__(self, calls):
        self.motion = FakeMotion(calls)
        self.calls = calls

    async def close(self):
        self.calls.append(("close",))


class FakeConfig:
    def __init__(self):
        self.extra = {}

    @classmethod
    def from_env(cls):
        return cls()


class AgentechCommandTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        async def fake_connect(target, config=None):
            self.calls.append(("connect", target, dict(config.extra)))
            return FakeSession(self.calls)

        fake_sdk = types.ModuleType("ff_sdk")
        fake_sdk.Config = FakeConfig
        fake_sdk.connect = fake_connect
        sys.modules["ff_sdk"] = fake_sdk

    def test_forward_is_real_forward_command_by_default(self):
        from agentech import Agentech

        os.environ["FF_SDK_DRY_RUN"] = "1"
        Agentech.forward(speed=0.3, seconds=0, stand_wait=0)

        self.assertEqual(os.environ["FF_SDK_DRY_RUN"], "0")
        self.assertIn(("connect", "D1-DEMO", {"d1_variant": "zsl-1w"}), self.calls)
        self.assertIn(("stand",), self.calls)
        self.assertIn(("cmd_vel", 0.3, 0.0), self.calls)
        self.assertIn(("stop",), self.calls)

    def test_backward_yaw_and_tilt_map_to_ff_sdk_calls(self):
        from agentech import Agentech

        with Agentech.robot(host="192.168.234.1", dry_run=False, stand_wait=0) as dog:
            dog.backward(speed=0.2, seconds=0)
            dog.yaw(speed=0.25, seconds=0)
            dog.look_up(angle=1, speed=0.5)
            dog.look_down(angle=1, speed=0.5)

        self.assertIn(("connect", "D1-DEMO", {"d1_host": "192.168.234.1", "d1_variant": "zsl-1w"}), self.calls)
        self.assertIn(("cmd_vel", -0.2, 0.0), self.calls)
        self.assertIn(("cmd_vel", 0.0, 0.25), self.calls)
        self.assertIn(("attitude_control", {"pitch_vel": 0.5}), self.calls)
        self.assertIn(("attitude_control", {"pitch_vel": -0.5}), self.calls)


if __name__ == "__main__":
    unittest.main()
