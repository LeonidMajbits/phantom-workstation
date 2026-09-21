import pathlib
import sys
import unittest

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from phantom_workstation.ax_diff import compute_ax_diff, compute_node_hash, flatten_tree


class TestAXDiff(unittest.TestCase):
    def setUp(self):
        self.tree_a = {
            "role": "AXApplication",
            "name": "TestApp",
            "children": [
                {
                    "role": "AXWindow",
                    "name": "Main Window",
                    "children": [
                        {"role": "AXButton", "name": "Submit", "value": "Off", "frame": "100,100,50,20"},
                        {"role": "AXTextField", "name": "Username", "value": "UserA", "frame": "100,130,100,20"},
                    ],
                }
            ],
        }

        self.tree_b = {
            "role": "AXApplication",
            "name": "TestApp",
            "children": [
                {
                    "role": "AXWindow",
                    "name": "Main Window",
                    "children": [
                        {"role": "AXButton", "name": "Submit", "value": "On", "frame": "100,100,50,20"},
                        {"role": "AXTextField", "name": "Username", "value": "UserA", "frame": "100,130,100,20"},
                        {"role": "AXStaticText", "name": "Success", "value": "Done", "frame": "100,160,80,20"},
                    ],
                }
            ],
        }

    def test_compute_node_hash(self):
        node = {"role": "AXButton", "name": "OK", "value": "1"}
        h1 = compute_node_hash(node)
        h2 = compute_node_hash(node)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_flatten_tree(self):
        flat = flatten_tree(self.tree_a)
        self.assertEqual(len(flat), 4)
        self.assertIn("/AXApplication:TestApp", flat)

    def test_initial_diff(self):
        res = compute_ax_diff(None, self.tree_a)
        self.assertEqual(res["mode"], "full_initial")
        self.assertEqual(res["added_count"], 4)
        self.assertIn("token_reduction_pct", res)
        self.assertIn("exceeded_raw", res)

    def test_mutation_diff(self):
        res = compute_ax_diff(self.tree_a, self.tree_b)
        self.assertEqual(res["mode"], "delta_patch")
        self.assertEqual(res["added_count"], 1)
        self.assertEqual(res["modified_count"], 1)
        self.assertEqual(res["removed_count"], 0)
        mod_node = res["mutations"]["modified"][0]
        self.assertIn("changes", mod_node)
        self.assertEqual(mod_node["changes"]["value"], {"old": "Off", "new": "On"})
        self.assertEqual(mod_node["old_value"], "Off")
        self.assertEqual(mod_node["new_value"], "On")

    def test_state_mutation_tracking(self):
        # Verify changes to enabled, focused, selected, expanded, and subrole are tracked
        t1 = {
            "role": "AXWindow",
            "name": "Win",
            "children": [
                {"role": "AXButton", "name": "B1", "enabled": True, "focused": False, "subrole": "AXCloseButton"},
                {"role": "AXCheckBox", "name": "C1", "selected": False, "expanded": False},
            ],
        }
        t2 = {
            "role": "AXWindow",
            "name": "Win",
            "children": [
                {"role": "AXButton", "name": "B1", "enabled": False, "focused": True, "subrole": "AXCloseButton"},
                {"role": "AXCheckBox", "name": "C1", "selected": True, "expanded": True},
            ],
        }
        res = compute_ax_diff(t1, t2)
        self.assertEqual(res["modified_count"], 2)
        mod_b1 = next(m for m in res["mutations"]["modified"] if m["name"] == "B1")
        self.assertEqual(mod_b1["changes"]["enabled"], {"old": True, "new": False})
        self.assertEqual(mod_b1["changes"]["focused"], {"old": False, "new": True})

        mod_c1 = next(m for m in res["mutations"]["modified"] if m["name"] == "C1")
        self.assertEqual(mod_c1["changes"]["selected"], {"old": False, "new": True})
        self.assertEqual(mod_c1["changes"]["expanded"], {"old": False, "new": True})

    def test_path_escaping_and_collision_resistance(self):
        # Sibling with literal slash vs nested node
        tree_slash = {
            "role": "AXWindow",
            "name": "Win",
            "children": [
                {"identifier": "a/b", "role": "AXButton", "name": "Slash"},
            ],
        }
        tree_nested = {
            "role": "AXWindow",
            "name": "Win",
            "children": [
                {"identifier": "a", "role": "AXGroup", "children": [
                    {"identifier": "b", "role": "AXButton", "name": "Child"}
                ]},
            ],
        }
        flat_slash = flatten_tree(tree_slash)
        flat_nested = flatten_tree(tree_nested)
        self.assertIn("/AXWindow:Win/a%2Fb", flat_slash)
        self.assertIn("/AXWindow:Win/a/b", flat_nested)
        self.assertNotIn("/AXWindow:Win/a/b", flat_slash)

        # Sibling disambiguation does not collide with literal #2
        tree_disambig = {
            "role": "AXWindow",
            "name": "Win",
            "children": [
                {"identifier": "item#2", "role": "AXButton"},
                {"identifier": "item", "role": "AXButton"},
                {"identifier": "item", "role": "AXButton"},
            ],
        }
        flat_d = flatten_tree(tree_disambig)
        self.assertEqual(len(flat_d), 4)
        self.assertIn("/AXWindow:Win/item%232", flat_d)
        self.assertIn("/AXWindow:Win/item", flat_d)
        self.assertIn("/AXWindow:Win/item#2", flat_d)

    def test_delimiter_collision_resistance(self):
        n1 = {"role": "A|B", "name": "C"}
        n2 = {"role": "A", "name": "B|C"}
        self.assertNotEqual(compute_node_hash(n1), compute_node_hash(n2))

    def test_large_tree_token_reduction(self):
        children_a = [{"role": "AXStaticText", "name": f"Label_{i}", "value": f"Text_{i}"} for i in range(40)]
        tree_large_a = {"role": "AXApplication", "name": "LargeApp", "children": children_a}

        # Modify only 1 element
        children_b = list(children_a)
        children_b[5] = {"role": "AXStaticText", "name": "Label_5", "value": "Modified_Text"}
        tree_large_b = {"role": "AXApplication", "name": "LargeApp", "children": children_b}

        res = compute_ax_diff(tree_large_a, tree_large_b)
        self.assertEqual(res["modified_count"], 1)
        self.assertGreater(res["token_reduction_pct"], 75.0)

    def test_sibling_insertion_does_not_shift_indices(self):
        children_a = [{"role": "AXButton", "name": f"Item_{i}", "value": f"Val_{i}"} for i in range(1, 11)]
        tree_a = {"role": "AXWindow", "name": "ListWindow", "children": children_a}

        children_b = [{"role": "AXButton", "name": "Item_0", "value": "Val_0"}] + list(children_a)
        tree_b = {"role": "AXWindow", "name": "ListWindow", "children": children_b}

        res = compute_ax_diff(tree_a, tree_b)
        self.assertEqual(res["added_count"], 1)
        self.assertEqual(res["modified_count"], 0)
        self.assertEqual(res["removed_count"], 0)
        self.assertEqual(res["mutations"]["added"][0]["name"], "Item_0")

    def test_none_curr_tree_handled_gracefully(self):
        res = compute_ax_diff(None, None)
        self.assertEqual(res["mode"], "empty_or_invalid")
        self.assertEqual(res["added_count"], 0)

    def test_malformed_children_handled_gracefully(self):
        bad_tree = {"role": "AXWindow", "children": "string_not_list"}
        res = compute_ax_diff(None, bad_tree)
        self.assertEqual(res["mode"], "full_initial")
        self.assertEqual(res["added_count"], 1)

    def test_cyclic_tree_does_not_infinite_recurse(self):
        node: dict = {"role": "AXWindow", "name": "Cyclic"}
        node["children"] = [node]  # Circular reference
        res = compute_ax_diff(None, node)
        self.assertEqual(res["mode"], "full_initial")
        self.assertEqual(res["added_count"], 1)


if __name__ == "__main__":
    unittest.main()
