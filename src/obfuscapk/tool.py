#!/usr/bin/env python3.7

import io
import logging
import os
import shutil
import subprocess
import zipfile
from typing import List


class Apktool(object):

    def __init__(self):
        self.logger = logging.getLogger('{0}.{1}'.format(__name__, self.__class__.__name__))

        if 'APKTOOL_PATH' in os.environ:
            self.apktool_path: str = os.environ['APKTOOL_PATH']
        else:
            self.apktool_path: str = 'apktool'

    def decode(self, apk_path: str, output_dir_path: str = None, force: bool = False) -> str:

        # Check if the apk file to decode is a valid file.
        if not os.path.isfile(apk_path):
            self.logger.error('Unable to find file "{0}"'.format(apk_path))
            raise FileNotFoundError('Unable to find file "{0}"'.format(apk_path))

        # If no output directory is specified, use a new directory in the same directory
        # as the apk file to decode.
        if not output_dir_path:
            output_dir_path = os.path.join(os.path.dirname(apk_path),
                                           os.path.splitext(os.path.basename(apk_path))[0])
            self.logger.debug('No output directory provided, the result will be saved in the '
                              'same directory as the input file, in a directory with the same '
                              'name as the input file: "{0}"'.format(output_dir_path))

        # If an output directory is provided, make sure that the path to that directory exists
        # (the final directory will be created by apktool).
        elif not os.path.isdir(os.path.dirname(output_dir_path)):
            self.logger.error('Unable to find output directory "{0}", apktool won\'t be able to create '
                              'the directory "{1}"'.format(os.path.dirname(output_dir_path), output_dir_path))
            raise NotADirectoryError('Unable to find output directory "{0}", apktool won\'t be able to create '
                                     'the directory "{1}"'.format(os.path.dirname(output_dir_path), output_dir_path))

        # Inform the user if an existing output directory is provided without the "force" flag.
        if os.path.isdir(output_dir_path) and not force:
            self.logger.error('Output directory "{0}" already exists, use the "force" flag to overwrite'
                              .format(output_dir_path))
            raise FileExistsError('Output directory "{0}" already exists, use the "force" flag to overwrite'
                                  .format(output_dir_path))

        decode_cmd: List[str] = [self.apktool_path, 'd', apk_path, '-o', output_dir_path]

        if force:
            decode_cmd.insert(2, '--force')

        try:
            self.logger.info('Running decode command "{0}"'.format(' '.join(decode_cmd)))
            output = subprocess.check_output(decode_cmd, stderr=subprocess.STDOUT).strip()
            return output.decode()
        except subprocess.CalledProcessError as e:
            self.logger.error('Error during decode command: {0}'.format(
                e.output.decode(errors='replace') if e.output else e))
            raise
        except Exception as e:
            self.logger.error('Error during decoding: {0}'.format(e))
            raise

    def build(self, source_dir_path: str, output_apk_path: str = None) -> str:

        # Check if the input directory exists.
        if not os.path.isdir(source_dir_path):
            self.logger.error('Unable to find source directory "{0}"'.format(source_dir_path))
            raise NotADirectoryError('Unable to find source directory "{0}"'.format(source_dir_path))

        # If no output apk path is specified, the new apk will be saved in the default path:
        # <source_dir_path>/dist/<source_dir_name>.apk
        if not output_apk_path:
            self.logger.debug('No output apk path provided, the new apk will be saved in the '
                              'default path: "{0}.apk"'
                              .format(os.path.join(source_dir_path, 'dist',
                                                   os.path.basename(os.path.normpath(source_dir_path)))))

        build_cmd: List[str] = [self.apktool_path, 'b', '--force-all', source_dir_path]

        if output_apk_path:
            build_cmd.extend(['-o', output_apk_path])

        try:
            self.logger.info('Running build command "{0}"'.format(' '.join(build_cmd)))
            output = subprocess.check_output(build_cmd, stderr=subprocess.STDOUT).strip()
            return output.decode()
        except subprocess.CalledProcessError as e:
            self.logger.error('Error during build command: {0}'.format(
                e.output.decode(errors='replace') if e.output else e))
            raise
        except Exception as e:
            self.logger.error('Error during building: {0}'.format(e))
            raise


class Jarsigner(object):

    def __init__(self):
        self.logger = logging.getLogger('{0}.{1}'.format(__name__, self.__class__.__name__))

        if 'JARSIGNER_PATH' in os.environ:
            self.jarsigner_path: str = os.environ['JARSIGNER_PATH']
        else:
            self.jarsigner_path: str = 'jarsigner'

    def sign(self, apk_path: str, keystore_file_path: str, keystore_password: str, key_alias: str) -> str:

        # Check if the apk file to sign is a valid file.
        if not os.path.isfile(apk_path):
            self.logger.error('Unable to find file "{0}"'.format(apk_path))
            raise FileNotFoundError('Unable to find file "{0}"'.format(apk_path))

        sign_cmd: List[str] = [self.jarsigner_path,
                               '-tsa', 'http://timestamp.comodoca.com/rfc3161',
                               '-sigalg', 'SHA1withRSA', '-digestalg', 'SHA1',
                               '-keystore', keystore_file_path,
                               '-storepass', keystore_password,
                               apk_path, key_alias]

        try:
            self.logger.info('Running sign command "{0}"'.format(' '.join(sign_cmd)))
            output = subprocess.check_output(sign_cmd, stderr=subprocess.STDOUT).strip()
            return output.decode()
        except subprocess.CalledProcessError as e:
            self.logger.error('Error during sign command: {0}'.format(
                e.output.decode(errors='replace') if e.output else e))
            raise
        except Exception as e:
            self.logger.error('Error during signing: {0}'.format(e))
            raise

    def resign(self, apk_path: str, keystore_file_path: str, keystore_password: str, key_alias: str) -> str:

        # If present, delete the old signature of the apk and then sign it with the new signature. Since python
        # doesn't allow directly deleting a file inside an archive, an OS independent solution is to create a
        # new archive without including the signature files.

        try:
            unsigned_apk_buffer = io.BytesIO()

            with zipfile.ZipFile(apk_path, 'r') as current_apk:
                # Check if the current apk is already signed.
                if any(entry.filename.startswith('META-INF/') for entry in current_apk.infolist()):

                    self.logger.info('Removing current signature from apk "{0}"'.format(apk_path))

                    # Create a new in-memory archive without the signature.
                    with zipfile.ZipFile(unsigned_apk_buffer, 'w') as unsigned_apk_zip_buffer:
                        for entry in current_apk.infolist():
                            if not entry.filename.startswith('META-INF/'):
                                unsigned_apk_zip_buffer.writestr(entry, current_apk.read(entry.filename))

                    # Write the in-memory archive to disk.
                    with open(apk_path, 'wb') as unsigned_apk:
                        unsigned_apk.write(unsigned_apk_buffer.getvalue())

        except Exception as e:
            self.logger.error('Error during the removal of the old signature: {0}'.format(e))
            raise

        return self.sign(apk_path, keystore_file_path, keystore_password, key_alias)


class Zipalign(object):

    def __init__(self):
        self.logger = logging.getLogger('{0}.{1}'.format(__name__, self.__class__.__name__))

        if 'ZIPALIGN_PATH' in os.environ:
            self.zipalign_path: str = os.environ['ZIPALIGN_PATH']
        else:
            self.zipalign_path: str = 'zipalign'

    def align(self, apk_path: str) -> str:

        # Check if the apk file to align is a valid file.
        if not os.path.isfile(apk_path):
            self.logger.error('Unable to find file "{0}"'.format(apk_path))
            raise FileNotFoundError('Unable to find file "{0}"'.format(apk_path))

        # Since zipalign cannot be run inplace, a temp file will be created.
        apk_copy_path = '{0}.copy.apk'.format(os.path.join(os.path.dirname(apk_path),
                                                           os.path.splitext(os.path.basename(apk_path))[0]))

        try:
            shutil.copy2(apk_path, apk_copy_path)

            align_cmd = [self.zipalign_path, '-f', '4', apk_copy_path, apk_path]

            self.logger.info('Running align command "{0}"'.format(' '.join(align_cmd)))
            output = subprocess.check_output(align_cmd, stderr=subprocess.STDOUT).strip()
            return output.decode()
        except subprocess.CalledProcessError as e:
            self.logger.error('Error during align command: {0}'.format(
                e.output.decode(errors='replace') if e.output else e))
            raise
        except Exception as e:
            self.logger.error('Error during aligning: {0}'.format(e))
            raise
        finally:
            # Remove the temp file used for zipalign.
            if os.path.isfile(apk_copy_path):
                os.remove(apk_copy_path)
