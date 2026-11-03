import unittest
import test_go_keys as keys


class Claims(keys.Claims):
    part = 3


if __name__ == "__main__":
    unittest.main(verbosity=2)
