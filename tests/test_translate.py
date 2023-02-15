import json
import os
from os.path import join

from translate import GameTranslator


TEST_DIR = os.path.dirname(__file__)


def test_valid():
    def mock_save_single_file(filename, got_data):
        with open(join(TEST_DIR, 'expected.json')) as f:
            expected = json.load(f)
        assert got_data == expected

    t = GameTranslator('skip', 60)
    t.from_path = TEST_DIR
    t.call_translator = lambda text: text
    t.save_single_file = mock_save_single_file
    t.process_single_file('input.json')
