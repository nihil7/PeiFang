import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from peifang_core.wecom import import_smartsheet_links, parse_smartsheet_link, verify_registry_doc_profiles


class WeComManualLinksTest(unittest.TestCase):
    def test_parse_smartsheet_link_extracts_doc_key_and_sanitizes_url(self):
        url = (
            "https://doc.weixin.qq.com/smartsheet/s3_ACcA4BQeAKQCNeXdy0roiSEWNZDNB_a"
            "?scode=AEsAtgeGADUH8nREgAACcA4BQeAKQ&version=5.0.8.6009"
            "&platform=win&tab=q979lj&viewId=vukaF8"
        )

        parsed = parse_smartsheet_link(url)

        self.assertEqual(parsed["docid"], "s3_ACcA4BQeAKQCNeXdy0roiSEWNZDNB_a")
        self.assertEqual(parsed["tab"], "q979lj")
        self.assertEqual(parsed["viewId"], "vukaF8")
        self.assertNotIn("scode=", parsed["safe_url"])
        self.assertNotIn("token=", parsed["safe_url"])

    def test_import_smartsheet_links_updates_registry_and_exports_review_table(self):
        class FakeClient:
            def get_sheets(self, docid):
                assert docid == "s3_ACcA4BQeAKQCNeXdy0roiSEWNZDNB_a"
                return [
                    {
                        "sheet_id": "sh_001",
                        "properties": {"title": "销售配方", "index": 1},
                        "creator_name": "王浩",
                        "create_time": 1710000000000,
                        "update_time": 1710003600000,
                    }
                ]

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "links.csv"
            registry = tmp_path / "registry.json"
            output_dir = tmp_path / "output"
            source.write_text(
                "company_profile,company_name,doc_name,url,enabled,remark\n"
                "COMPANY_A,四川和裕达新材料有限公司,人工表,"
                "https://doc.weixin.qq.com/smartsheet/s3_ACcA4BQeAKQCNeXdy0roiSEWNZDNB_a"
                "?scode=secret&tab=q979lj&viewId=vukaF8,yes,重点核对\n",
                encoding="utf-8",
            )

            result = import_smartsheet_links(
                source_path=source,
                registry_path=registry,
                output_dir=output_dir,
                client_factory=lambda profile, credential: FakeClient(),
                credentials_provider=lambda profile: [{"corpid": "ww", "secret": "sec", "app_label": "default"}],
            )

            self.assertEqual(result["imported_doc_count"], 1)
            self.assertEqual(result["ok_doc_count"], 1)
            self.assertEqual(Path(result["latest_xlsx_path"]).name, "wecom_smartsheet_link_inventory.xlsx")
            self.assertTrue(registry.exists())
            self.assertNotIn("scode=secret", registry.read_text(encoding="utf-8"))

    def test_verify_registry_doc_profiles_corrects_wrong_company(self):
        class FakeClient:
            def __init__(self, profile):
                self.profile = profile

            def get_sheets(self, docid):
                if self.profile == "COMPANY_B":
                    return [{"sheet_id": "sh_b", "properties": {"title": "B表", "index": 1}}]
                raise RuntimeError("no access")

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            registry = tmp_path / "registry.json"
            output_dir = tmp_path / "output"
            registry.write_text(
                '{"docs":{"s3_ACcA4BQeAKQCNeXdy0roiSEWNZDNB_a":'
                '{"docid":"s3_ACcA4BQeAKQCNeXdy0roiSEWNZDNB_a","doc_name":"错归属","env_profile":"COMPANY_A","sheets":{}}}}',
                encoding="utf-8",
            )

            result = verify_registry_doc_profiles(
                profiles=["COMPANY_A", "COMPANY_B"],
                registry_path=registry,
                output_dir=output_dir,
                client_factory=lambda profile, credential: FakeClient(profile),
                credentials_provider=lambda profile: [{"corpid": "ww", "secret": "sec", "app_label": "default"}],
            )

            self.assertEqual(result["corrected_count"], 1)
            text = registry.read_text(encoding="utf-8")
            self.assertIn('"env_profile": "COMPANY_B"', text)
            self.assertTrue(Path(result["latest_xlsx_path"]).exists())


if __name__ == "__main__":
    unittest.main()
