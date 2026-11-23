import unittest

class SignUp(unittest.TestCase):
    def test_AUTH_001_S1_signs_up(self):
        pass

    @unittest.skip("later")
    def test_AUTH_001_S10_also_works(self):
        pass

@unittest.skip("whole class")
class Off(unittest.TestCase):
    def test_AUTH_001_S10_in_a_skipped_class(self):
        pass
