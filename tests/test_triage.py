import subprocess
from pathlib import Path


def test_clinical_characterization_unchanged():
    result=subprocess.run(['node','-'],cwd=Path(__file__).resolve().parents[1],input=r'''
const vm=require('vm'),fs=require('fs');
const c=vm.createContext({window:{}});
vm.runInContext(fs.readFileSync('js/risk-triage.js','utf8'),c);
const t=c.window.RiskTriage;
const checks=[
 t.assessText('')===null,t.assessText('Hello')===null,
 t.assessText('vaginal bleeding during pregnancy').priority==='URGENT',
 t.assessText('postpartum hemorrhage').priority==='HIGH-MODERATE',
 t.assessConversation([{role:'bot',message:'vaginal bleeding during pregnancy'}])===null,
 t.assessConversation([{message:'vaginal bleeding during pregnancy'}]).priority==='URGENT',
 t.assessConversation([{role:'user',message:'postpartum hemorrhage'},{role:'user',message:'vaginal bleeding during pregnancy'}]).priority==='URGENT',
 t.assessText('I do not have vaginal bleeding during pregnancy')!==null
];
if(checks.some(x=>!x))process.exit(1);
''',text=True,capture_output=True)
    assert result.returncode==0
