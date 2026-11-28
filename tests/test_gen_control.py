import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import gen_control  # noqa: E402
import isa  # noqa: E402


class GenControl(unittest.TestCase):
    def test_committed_image_is_up_to_date(self):
        self.assertEqual(gen_control.main(["--check"]), 0)

    def test_image_matches_rom(self):
        lines = gen_control.control_hex().splitlines()
        self.assertEqual(lines[0], "v2.0 raw")
        words = [int(w, 16) for line in lines[1:] for w in line.split()]
        self.assertEqual(words, [c.word for c in isa.control_rom()])

    def test_check_catches_stale_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "control.hex"
            self.assertEqual(gen_control.main(["-o", str(out), "--check"]), 1)
            out.write_text(gen_control.control_hex().replace("000000", "000001", 1))
            self.assertEqual(gen_control.main(["-o", str(out), "--check"]), 1)
            self.assertEqual(gen_control.main(["-o", str(out)]), 0)
            self.assertEqual(gen_control.main(["-o", str(out), "--check"]), 0)


if __name__ == "__main__":
    unittest.main()
