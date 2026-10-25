import tempfile
import unittest
from pathlib import Path
from test_pipeline import candidate
import review_release


class ArtifactReviewTests(unittest.TestCase):
    def test_uploaded_rendered_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sample = root / 'rendered/qa_samples/reviewed-sample'
            sample.mkdir(parents=True)
            self.assertEqual(sample, review_release.artifact_sample(root, 'reviewed-sample'))

    def test_legacy_flattened_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sample = root / 'qa_samples/reviewed-sample'
            sample.mkdir(parents=True)
            self.assertEqual(sample, review_release.artifact_sample(root, 'reviewed-sample'))

    def test_missing_and_ambiguous_layouts_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                review_release.artifact_sample(root, 'reviewed-sample')
            (root / 'qa_samples/reviewed-sample').mkdir(parents=True)
            (root / 'rendered/qa_samples/reviewed-sample').mkdir(parents=True)
            with self.assertRaises(ValueError):
                review_release.artifact_sample(root, 'reviewed-sample')

    def test_folder_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                review_release.artifact_sample(Path(temp), '../other-folder')


if __name__ == '__main__':
    unittest.main()
