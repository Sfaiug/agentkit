import unittest
import test_go_keys as keys


class Claims(keys.Claims):
    part = 2


if __name__ == "__main__":
    unittest.main(verbosity=2)
