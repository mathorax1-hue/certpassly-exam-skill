import importlib.util, pathlib, unittest
p=pathlib.Path(__file__).resolve().parents[1]/'scripts'/'audit_v2_interaction_structure.py'; spec=importlib.util.spec_from_file_location('audit',p);audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
def base():
 return {'question_key':'q001','version':1,'type':'single_choice','learner':{'stem':{'format':'html','text':'<p>Good</p>'},'interaction':{'options':[{'id':'a','text':'A'},{'id':'b','text':'B'}],'choose_n':1}}}
class Tests(unittest.TestCase):
 def test_good(self):self.assertEqual(audit.audit_one(base(),'q001.v1.json')['errors'],[])
 def test_version_mismatch(self):
  x=base();x['version']=2;self.assertIn('file version mismatch',audit.audit_one(x,'q001.v1.json')['errors'])
 def test_bad_nested_answer(self):
  x=base();x['learner']['interaction']['correct_answers']=['a'];self.assertIn('answer material embedded in learner object',audit.audit_one(x,'q001.v1.json')['errors'])
 def test_unsafe_javascript_url(self):
  x=base();x['learner']['stem']['text']='<p><a href="javascript:alert(1)">Click</a></p>';self.assertIn('unsafe HTML detected',audit.audit_one(x,'q001.v1.json')['errors'])
 def test_unsafe_svg(self):
  x=base();x['learner']['stem']['text']='<svg><circle onload="evil()"/></svg>';self.assertIn('unsafe HTML detected',audit.audit_one(x,'q001.v1.json')['errors'])
 def test_media_path_traversal(self):
  x=base();x['learner']['media']=[{'href':'/media/../../secret'}];self.assertIn('invalid learner media href',audit.audit_one(x,'q001.v1.json')['errors'])
 def test_nonobject(self):self.assertIn('document is not an object',audit.audit_one(None,'q001.v1.json')['errors'])
 def test_nonlist_media(self):
  x=base();x['learner']['media']={};self.assertIn('malformed learner media',audit.audit_one(x,'q001.v1.json')['errors'])
if __name__=='__main__':unittest.main()