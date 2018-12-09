#!/usr/bin/env python

import logging
import tempfile
import shutil
import zipfile
import filecmp
import unittest
import os

import j2i


def get_path_to_expected_files(tc_name):
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), 'tests', tc_name))


class _BaseTestCase(unittest.TestCase):
    """Extend unittest.TestCase with more functionality"""
    def __init__(self, *args, **kwargs):
        super(_BaseTestCase, self).__init__(*args, **kwargs)
        self.addTypeEqualityFunc(str, self.assertEqualWithDiff)

    def assertEqualWithDiff(self, left, right, msg=None):
        import difflib
        try:
            self._baseAssertEqual(left, right)
        except self.failureException:
            diff = difflib.unified_diff(
                left.splitlines(True),
                right.splitlines(True),
                n=0
            )
            diff = ''.join(diff)
            raise self.failureException("{0}\n{1}".format(msg or '', diff))


class J2iTest(_BaseTestCase):

    def setUp(self):
        # show all differences
        self.maxDiff = None

        # disable logging temporarily to reduce spam
        logging.getLogger().setLevel(logging.WARNING)

        # create a temp dir to store the result
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        # remove the temp dir created
        os.chdir(os.path.expanduser("~"))
        shutil.rmtree(self.tmp_dir)

    def test_examples(self):
        input_file = os.path.abspath(
            os.path.join(os.path.dirname(__file__), 'examples/input.yaml'))

        templates = os.path.abspath(
            os.path.join(os.path.dirname(__file__), 'examples/templates'))

        self.run_test('examples', input_file, templates)

    def run_test(self, tc_name, path_to_input_file, path_to_templates):
        # create the list of arguments
        args = [
            '-i', path_to_input_file,
            '-t', path_to_templates,
            '-o', tc_name
        ]

        exp_dir = get_path_to_expected_files(tc_name)

        # create the output file in the tmp dir
        os.chdir(self.tmp_dir)
        j2i.main(args)

        # make sure the output file was created
        output_file = os.path.join(self.tmp_dir, tc_name + '.zip')
        self.assertTrue(os.path.isfile(output_file))

        # create a temp dir to store the extracted zip file
        tmp_dir = tempfile.mkdtemp()
        try:
            # extract the zip file
            zf = zipfile.ZipFile(output_file, 'r')
            zf.extractall(tmp_dir)
        except BaseException as e:
            self.fail("Failed to create tmp dir: {}".format(e))
        else:
            self.compare_dirs(exp_dir, tmp_dir)
        finally:
            # remove tempdir for unzipped files
            shutil.rmtree(tmp_dir)

    def compare_dirs(self, dir1, dir2):
        """Compare the content of two directories recursively
        """
        # make sure that expected files are included
        dirs_cmp = filecmp.dircmp(dir1, dir2)
        self.assertTrue(len(dirs_cmp.left_only) == 0,
                        "Some files are missing from the output: {0}"
                        .format(dirs_cmp.left_only))
        self.assertTrue(len(dirs_cmp.right_only) == 0,
                        "Output contains more files than "
                        "expected: {0}".format(dirs_cmp.right_only))

        self.assertTrue(len(dirs_cmp.funny_files) == 0,
                        "Some files could not be compared: {0}"
                        .format(dirs_cmp.funny_files))

        # compare the files content
        (_, mismatch, errors) = filecmp.cmpfiles(
            dir1, dir2, dirs_cmp.common_files, shallow=False)

        for mf in mismatch:
            with open(os.path.join(dir1, mf)) as f:
                f1 = f.read()
            with open(os.path.join(dir2, mf)) as f:
                f2 = f.read()

            self.assertEqualWithDiff(f1, f2,
                                     "File '{0}' is different"
                                     .format(os.path.join(dir1, mf)))

        self.assertTrue(len(errors) == 0,
                        "Some files could not be compared: {0}".format(errors))

        # recurse into subdirs
        for common_dir in dirs_cmp.common_dirs:
            new_dir1 = os.path.join(dir1, common_dir)
            new_dir2 = os.path.join(dir2, common_dir)
            self.compare_dirs(new_dir1, new_dir2)


if __name__ == "__main__":
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(J2iTest))
    unittest.TextTestRunner().run(suite)
