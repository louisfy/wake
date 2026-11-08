import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'script'))
from privacy_check import check_bytes,check_archive
from fetch_runtime import extract,license_paths
from public_files import public_files
from zip_app import pack


class PublicationTests(unittest.TestCase):
    def test_all_upstream_license_field_formats_are_preserved(self):
        data=dict(license_path='python.txt',extensions=[dict(license_paths=['ssl.txt','ffi.txt'])])
        self.assertEqual(license_paths(data),{'python.txt','ssl.txt','ffi.txt'})

    def test_secret_and_personal_path_fail_without_echoing_value(self):
        values=[b'/' + b'Users/person/project', b'ghp_' + b'a'*36,
                b'-----BEGIN ' + b'PRIVATE KEY-----', b'https://' + b'name:password@example.test/']
        for value in values:
            with self.assertRaises(ValueError) as error:check_bytes('fixture',value)
            self.assertNotIn(value.decode(),str(error.exception))

    def test_runtime_data_and_macos_metadata_are_rejected(self):
        for name in ('App.app/Runtime/service.log','__MACOSX/._icon','App.app/products.json'):
            with tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'fixture.zip'
                with zipfile.ZipFile(path,'w') as archive:archive.writestr(name,b'fixture')
                with self.assertRaises(ValueError):check_archive(path)

    def test_public_export_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'README.md').symlink_to('/etc/hosts')
            with self.assertRaises(ValueError):public_files(root)

    def test_runtime_archive_cannot_escape_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'fixture.tar.gz'
            with tarfile.open(path,'w:gz') as archive:
                item=tarfile.TarInfo('python/../../escape');item.size=1
                archive.addfile(item,io.BytesIO(b'x'))
            with self.assertRaises(ValueError):extract(path,Path(temp)/'output')

    def test_app_zip_keeps_unicode_and_execute_bits_but_rejects_external_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle=root/'云朵.app'
            executable=bundle/'Contents/MacOS/Entry'
            executable.parent.mkdir(parents=True);executable.write_text('fixture');executable.chmod(0o755)
            archive=root/'fixture.zip'
            pack(bundle,archive)
            with zipfile.ZipFile(archive) as file:
                info=file.getinfo('云朵.app/Contents/MacOS/Entry')
                self.assertTrue(info.flag_bits & 0x800)
                self.assertTrue((info.external_attr>>16)&0o111)
            (bundle/'outside').symlink_to('/etc/hosts')
            with self.assertRaises(ValueError):pack(bundle,archive)


if __name__=='__main__':unittest.main()
