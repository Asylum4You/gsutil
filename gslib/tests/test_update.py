# Copyright 2013 Google Inc. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

"""Tests for the update command."""

import os.path
import shutil
import subprocess
import sys
import tarfile

import gslib
import gslib.tests.testcase as testcase
from gslib.tests.util import ObjectToURI as suri
from gslib.tests.util import unittest
from gslib.util import BOTO_IS_SECURE


TESTS_DIR = os.path.abspath(os.path.dirname(__file__))
GSUTIL_DIR = os.path.join(TESTS_DIR, '..', '..')


class UpdateTest(testcase.GsUtilIntegrationTestCase):
  """Update command test suite."""

  @unittest.skipUnless(BOTO_IS_SECURE[0],
                       'Test requires boto secure connection.')
  def test_update(self):
    """Tests that the update command works or throws proper exceptions."""

    if gslib.IS_PACKAGE_INSTALL:
      # The update command is not present when installed via package manager.
      stderr = self.RunGsUtil(['update'], return_stderr=True, expected_status=1)
      self.assertIn('Invalid command', stderr)
      return

    # Create two temp directories, one of which we will run 'gsutil update' in
    # to pull the changes from the other.
    tmpdir_src = self.CreateTempDir()
    tmpdir_dst = self.CreateTempDir()

    # Copy gsutil to both source and destination directories.
    gsutil_src = os.path.join(tmpdir_src, 'gsutil')
    gsutil_dst = os.path.join(tmpdir_dst, 'gsutil')
    shutil.copytree(GSUTIL_DIR, gsutil_src)
    # Copy specific files rather than all of GSUTIL_DIR so we don't pick up temp
    # working files left in top-level directory by gsutil developers (like tags,
    # .git*, etc.)
    os.makedirs(gsutil_dst)
    for comp in ('CHANGES.md', 'CHECKSUM', 'COPYING', 'gslib', 'gsutil',
                 'LICENSE.third_party', 'MANIFEST.in', 'README.md', 'scripts',
                 'setup.py', 'third_party', 'VERSION'):
      if os.path.isdir(os.path.join(GSUTIL_DIR, comp)):
        func = shutil.copytree
      else:
        func = shutil.copyfile
      func(os.path.join(GSUTIL_DIR, comp), os.path.join(gsutil_dst, comp))

    # Create a fake version number in the source so we can verify it in the
    # destination.
    expected_version = '17.25'
    src_version_file = os.path.join(gsutil_src, 'VERSION')
    self.assertTrue(os.path.exists(src_version_file))
    with open(src_version_file, 'w') as f:
      f.write(expected_version)

    # Create a tarball out of the source directory and copy it to a bucket.
    src_tarball = os.path.join(tmpdir_src, 'gsutil.test.tar.gz')

    normpath = os.path.normpath
    try:
      # We monkey patch os.path.normpath here because the tarfile module
      # normalizes the ./gsutil path, but the update command expects the tar
      # file to be prefixed with . This preserves the ./gsutil path.
      os.path.normpath = lambda fname: fname
      tar = tarfile.open(src_tarball, 'w:gz')
      tar.add(gsutil_src, arcname='./gsutil')
      tar.close()
    finally:
      os.path.normpath = normpath

    prefix = [sys.executable] if sys.executable else []

    # Run with an invalid gs:// URI.
    p = subprocess.Popen(prefix + ['gsutil', 'update', 'gs://pub'],
                         cwd=gsutil_dst, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    (_, stderr) = p.communicate()
    self.assertEqual(p.returncode, 1)
    self.assertIn('update command only works with tar.gz', stderr)

    # Run with non-existent gs:// URI.
    p = subprocess.Popen(
        prefix + ['gsutil', 'update', 'gs://pub/Jdjh38)(;.tar.gz'],
        cwd=gsutil_dst, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (_, stderr) = p.communicate()
    self.assertEqual(p.returncode, 1)
    self.assertIn('non-existent object', stderr)

    # Run with file:// URI wihout -f option.
    p = subprocess.Popen(prefix + ['gsutil', 'update', suri(src_tarball)],
                         cwd=gsutil_dst, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    (_, stderr) = p.communicate()
    self.assertEqual(p.returncode, 1)
    self.assertIn('command does not support', stderr)

    # Run with a file present that was not distributed with gsutil.
    with open(os.path.join(gsutil_dst, 'userdata.txt'), 'w') as fp:
      fp.write('important data\n')
    p = subprocess.Popen(prefix + ['gsutil', 'update', '-f', suri(src_tarball)],
                         cwd=gsutil_dst, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    (_, stderr) = p.communicate()
    # Clean up before next test, and before assertions so failure doesn't leave
    # this file around.
    os.unlink(os.path.join(gsutil_dst, 'userdata.txt'))
    self.assertEqual(p.returncode, 1)
    self.assertIn(
        'The update command cannot run with user data in the gsutil directory',
        stderr.replace('\n', ' '))

    # Now do the real update, which should succeed.
    p = subprocess.Popen(prefix + ['gsutil', 'update', '-f', suri(src_tarball)],
                         cwd=gsutil_dst, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    (_, stderr) = p.communicate(input='y\r\n')
    self.assertEqual(p.returncode, 0, msg=(
        'Non-zero return code (%d) from gsutil update. stderr = \n%s' %
        (p.returncode, stderr)))

    # Verify that version file was updated.
    dst_version_file = os.path.join(tmpdir_dst, 'gsutil', 'VERSION')
    with open(dst_version_file, 'r') as f:
      self.assertEqual(f.read(), expected_version)
