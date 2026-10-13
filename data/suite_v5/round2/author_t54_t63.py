"""Independent authoring for CDC, winner selection, SCD and reports (T54-T63)."""
from rw2_common import *
import re,xml.etree.ElementTree as ET
F=field; Q=decimal
DATE=lambda n,nullable=True:F(n,'date',nullable,format='yyyy-MM-dd HH:mm:ss')
D0='2026-01-01 00:00:00'
BASE=[F('business_ref',nullable=False),F('tenant_cd',nullable=False),F('source_file',nullable=False),F('source_row','long',False),DATE('received_at',False),F('currency_cd',nullable=False),F('operator_note'),F('market_cd'),F('owner_team'),F('trace_id'),F('unused_archive_label'),Q('context_value')]
def row(fields,**v):
 d={f['name']:(None if f['nullable']=='true' else {'string':'','integer':0,'long':0,'decimal':'0.00','boolean':False,'date':D0}.get(f['type'])) for f in fields}
 d.update(v);return d
def base(fields,key,n,**v):return row(fields,business_ref=key,tenant_cd='T1',source_file='feed.csv',source_row=n,received_at=D0,currency_cd='EUR',operator_note=('' if n%2 else None),market_cd='CZ',owner_team=None,trace_id='r'+str(n),unused_archive_label='old-'+str(n),context_value=None,**v)
def output(fields,src,**v):
 d={f['name']:src[f['name']] for f in fields if f['name'] in src};d.update(v);return row(fields,**d)
def save_scalars(fields,prefix='w',source='$in.0'):
 decl='\n'.join(f"{f['type']} {prefix}_{f['name']};" for f in fields)+'\n'
 save=''.join(f"{prefix}_{f['name']}={source}.{f['name']};" for f in fields)
 emit=''.join(f"$out.0.{f['name']}={prefix}_{f['name']};" for f in fields)
 return decl,save,emit
def oldmeta(tid):return [ET.fromstring(x) for x in re.findall(r'```xml\n(.*?)\n```',OLD[tid]['user_message'],re.S)]
def fieldsrec(r):return [dict(f.attrib) for f in r.findall('Field')]
def fixture(inp,exp):return {'inputs':inp,'expected':exp}
def checks(clauses,statements):return [(s,'The numbered business contract requires this behavior.',[i+1]) for i,s in enumerate(statements)]
items=[]
# T54: semantic membership changes differ from typed product tuple comparison.
fi=BASE+[F('tier_txt'),F('interests_txt'),Q('credit_limit'),DATE('consent_until')]
fo=fi+[F('change_names',nullable=False),F('notice_kind',nullable=False)]
clauses=[
'The DataIntersection receives yesterday on input 0 and today on input 1. Both are sorted by business_ref; join key is $business_ref=$business_ref. Equal NULL and Allow key duplicates are true. Ports 0 and 2 carry departures and arrivals unchanged; only a matched customer needs a notice decision.',
'For membership tier comparison alone, null, empty and whitespace mean the same absent tier; otherwise trim and uppercase. Keep the original tier text in the delivered record, including unrecognised codes.',
'Interpret interests_txt as semicolon-separated tokens. Discard blank tokens, trim and uppercase each remaining token, ignore repeated tokens, and compare the resulting sets without regard to their order. Null and empty are both the empty set; punctuation and text such as BAD:DATE are ordinary interest names.',
'Credit has changed if exactly one credit_limit is null, or when both are present and their absolute decimal difference is at least 0.05. Two nulls agree; a smaller difference is deliberately ignored. Do not round before this decision.',
'consent_until is compared as a complete nullable timestamp. Two nulls agree; null differs from every real date, and a midnight timestamp remains a real value. A time-only change within the same day matters.',
'Emit a NOTICE on the matched stream only when at least one semantic comparison changed. Its change_names lists TIER, INTERESTS, CREDIT, CONSENT in that order for the comparisons that changed, comma-separated without extra punctuation. A semantically unchanged pair produces no notice.',
'The notice carries every source field from today, even when a raw field differed but its normalised interpretation did not. Never replace the raw interest text with the canonical set or take yesterday\'s audit context.',
'Repeated keys produce their component-defined individual comparisons; no seen-key filter is allowed. Two old B rows and one new B row generate separate pairs. Decisions must not retain a prior pair\'s reason names. The first match and the final match follow the same rules as all intermediate pairs.'
]
code='''function string tier(string s) {return isnull(s) ? "" : upperCase(trim(s));}
function string interests(string s) {
 string[] a; if (!isnull(s)) {string[] p=split(s,";");foreach(string x:p) {string y=upperCase(trim(x));if(y!="" && !in(y,a)) append(a,y);}}
 sort(a);return join(";",a);
}
function integer transform() {
 string[] reasons;
 if(tier($in.0.tier_txt)!=tier($in.1.tier_txt)) append(reasons,"TIER");
 if(interests($in.0.interests_txt)!=interests($in.1.interests_txt)) append(reasons,"INTERESTS");
 boolean credit=false;
 if(isnull($in.0.credit_limit)!=isnull($in.1.credit_limit)) credit=true;
 else if(!isnull($in.0.credit_limit)) credit=abs($in.0.credit_limit-$in.1.credit_limit)>=0.05D;
 if(credit) append(reasons,"CREDIT");
 if($in.0.consent_until!=$in.1.consent_until) append(reasons,"CONSENT");
 if(length(reasons)==0) return SKIP;
 $out.0.*=$in.1.*;$out.0.notice_kind="NOTICE";$out.0.change_names=join(",",reasons);return OK;
}'''
a=[base(fi,'A',1,tier_txt=None,interests_txt=None),base(fi,'B',2,tier_txt=' silver ',interests_txt='shoe;SHOE',credit_limit='1.00'),base(fi,'B',3,tier_txt='GOLD',interests_txt='shoe',credit_limit='1.00'),base(fi,'C',4,tier_txt='VIP',interests_txt='BAD:DATE',credit_limit='2.00',consent_until=D0),base(fi,'D',5)]
b=[base(fi,'A',6,tier_txt='',interests_txt=' ; '),base(fi,'B',7,tier_txt='SILVER',interests_txt='SHOE;hat',credit_limit='1.04'),base(fi,'C',8,tier_txt='VIP',interests_txt='bad:date',credit_limit='2.05',consent_until='2026-01-01 00:00:01'),base(fi,'E',9,tier_txt='START')]
items.append(make('T54',4,'DataIntersection','Membership notices after semantic reconciliation','A loyalty operator wants useful change notifications rather than a byte-by-byte snapshot diff. Departure and arrival handlers already consume the one-sided streams; the CTL is confined to the middle reconciliation stream.',clauses,[('Member',fi),('Member',fi)],[('Member',fi),('Notice',fo),('Member',fi)],code,checks(clauses,['Honours matched-only DataIntersection behavior and pass-through ports.','Uses absent-tier equivalence while preserving raw tier.','Compares unique normalised interest sets, retaining punctuation as text.','Implements the exact 0.05 decimal threshold and symmetric credit-null handling.','Uses null-safe complete-date equality, including midnight/time differences.','Skips semantic equals and emits NOTICE with complete ordered change_names.','Copies every incoming source field without canonicalising the output.','Handles independent Cartesian duplicate pairs and fresh per-pair reasons.']), [('Must not invent left-only or right-only callbacks to build pass-through rows.','Those records bypass CTL.'),('Must not compare raw interests, round the credit delta, or suppress duplicate matches.','Each would contradict a business equivalence rule.')],fixture([a,b],{'0':[a[4]],'1':[output(fo,b[1],change_names='INTERESTS',notice_kind='NOTICE'),output(fo,b[1],change_names='TIER,INTERESTS',notice_kind='NOTICE'),output(fo,b[2],change_names='CREDIT,CONSENT',notice_kind='NOTICE')],'2':[b[3]]}),settings={'joinKey':'$business_ref=$business_ref','equalNULL':True,'keyDuplicates':True},traps=['canonical-set comparison','decimal tolerance boundary','duplicate Cartesian pairs']))
# T55: full outer settlement reconciliation with parse precedence.
left=BASE+[Q('expected_amount'),DATE('due_at'),F('invoice_note')]
right=BASE+[F('settled_txt'),F('settlement_state'),DATE('bank_at')]
out=BASE+[Q('expected_amount'),Q('settled_amount'),Q('remaining_amount'),F('reconcile_kind',nullable=False),F('error_reason',nullable=False)]
clauses=[
'An ExtMergeJoin uses FULL_OUTER joining on business_ref, ascending sorted inputs, with planned invoices on input 0 and bank entries on input 1. Both keys are non-null and unique per input. Port 0 is the settlement follow-up writer and port 1 is the data-repair queue.',
'Choose the audit context from the planned invoice whenever that side exists, including for a matched pair. A bank-only row instead takes its context from the bank record. An absent side has no usable key; a present side may contain nullable amounts and blank notes.',
'A bank record whose settlement_state is exactly VOID contributes decimal zero regardless of its settled_txt. In particular a VOID row with garbage text must not be parsed or rejected. Other spellings, null and empty state have no such exemption.',
'Otherwise settled_txt must be nonblank after trimming and match an optional minus sign followed by ASCII digits and an optional decimal part of one or two digits. Leading plus, exponents and commas are invalid. Accepted values have at most 10 integer digits and are parsed as decimals. A malformed present bank amount goes to repair with AMOUNT_TEXT.',
'A present invoice with null expected_amount goes to repair with EXPECTED_NULL unless malformed bank text already selected AMOUNT_TEXT. Negative planned or settled amounts are legitimate corrections. On repair rows settled_amount and remaining_amount are null even if some other quantity was usable.',
'For valid comparisons, a missing invoice means expected_amount zero, and a missing bank entry means settled_amount zero. Compute remaining_amount as expected minus settled using exact decimals. Always retain those three computed quantities on a follow-up row.',
'A valid matched pair with remaining_amount zero is omitted. All one-sided rows are retained even if their amount is zero. Label an invoice-only row WAITING and a bank-only row UNPLANNED; for a matched nonzero remainder use SHORT when positive and EXCESS when negative.',
'For repair output use reconcile_kind REPAIR and the selected error_reason. For follow-up output error_reason is empty. Write every context field, keep null distinct from empty and preserve the merger\'s output order within each destination. A date-only midnight and unparsed date-looking notes are ordinary context.',
'The first invoice-only, a first bank-only, zero corrections, and the final matched pair all use the same side-presence and precedence rules. Never substitute a numeric default for a present null invoice or emit a repair and follow-up copy of one pair.'
]
code='''function integer transform() {
 boolean l=!isnull($in.0.business_ref);boolean r=!isnull($in.1.business_ref);
 if(l) {$out.0.*=$in.0.*;$out.1.*=$in.0.*;} else {$out.0.*=$in.1.*;$out.1.*=$in.1.*;}
 decimal e=l ? $in.0.expected_amount : 0D;decimal s=0D;string err="";
 if(r && $in.1.settlement_state!="VOID") {
  string txt=isnull($in.1.settled_txt) ? "" : trim($in.1.settled_txt);
  if(!(txt ~= "-?[0-9]{1,10}(\\\\.[0-9]{1,2})?")) err="AMOUNT_TEXT";else s=str2decimal(txt);
 }
 if(err=="" && l && isnull(e)) err="EXPECTED_NULL";
 if(err!="") {$out.1.expected_amount=e;$out.1.settled_amount=null;$out.1.remaining_amount=null;$out.1.reconcile_kind="REPAIR";$out.1.error_reason=err;return 1;}
 decimal delta=e-s;if(l && r && delta==0D) return SKIP;
 $out.0.expected_amount=e;$out.0.settled_amount=s;$out.0.remaining_amount=delta;$out.0.error_reason="";
 $out.0.reconcile_kind=!l ? "UNPLANNED" : (!r ? "WAITING" : (delta>0D ? "SHORT" : "EXCESS"));return 0;
}'''
a=[base(left,'A',1,expected_amount='10.00',due_at=D0),base(left,'C',2,expected_amount=None),base(left,'D',3,expected_amount='10.00'),base(left,'E',4,expected_amount='0.00'),base(left,'F',5,expected_amount='-2.00')]
b=[base(right,'B',6,settled_txt='0',settlement_state='POSTED'),base(right,'C',7,settled_txt='1e2',settlement_state='POSTED'),base(right,'D',8,settled_txt='7.50',settlement_state='POSTED'),base(right,'E',9,settled_txt='2025-02-30',settlement_state='VOID'),base(right,'F',10,settled_txt='-3',settlement_state='POSTED')]
exp0=[output(out,a[0],expected_amount='10.00',settled_amount='0.00',remaining_amount='10.00',reconcile_kind='WAITING',error_reason=''),output(out,b[0],expected_amount='0.00',settled_amount='0.00',remaining_amount='0.00',reconcile_kind='UNPLANNED',error_reason=''),output(out,a[2],expected_amount='10.00',settled_amount='7.50',remaining_amount='2.50',reconcile_kind='SHORT',error_reason=''),output(out,a[4],expected_amount='-2.00',settled_amount='-3.00',remaining_amount='1.00',reconcile_kind='SHORT',error_reason='')]
exp1=[output(out,a[1],expected_amount=None,settled_amount=None,remaining_amount=None,reconcile_kind='REPAIR',error_reason='AMOUNT_TEXT')]
a.extend([base(left,'G',11,expected_amount=None),base(left,'H',12,expected_amount='1.00'),base(left,'I',13,expected_amount='0.00')])
b.extend([base(right,'G',14,settled_txt='0',settlement_state='POSTED'),base(right,'H',15,settled_txt='2',settlement_state='POSTED')])
exp1.append(output(out,a[5],expected_amount=None,settled_amount=None,remaining_amount=None,reconcile_kind='REPAIR',error_reason='EXPECTED_NULL'))
exp0.extend([output(out,a[6],expected_amount='1.00',settled_amount='2.00',remaining_amount='-1.00',reconcile_kind='EXCESS',error_reason=''),output(out,a[7],expected_amount='0.00',settled_amount='0.00',remaining_amount='0.00',reconcile_kind='WAITING',error_reason='')])
items.append(make('T55',4,'ExtMergeJoin','Bank settlement gaps with absent partners','Treasury reconciles expected invoices against a bank extract. The join is deliberately full outer because both unexplained deposits and unpaid invoices matter; a bad amount belongs to repair rather than the settlement queue.',clauses,[('Planned',left),('Bank',right)],[('FollowUp',out),('FollowUp',out)],code,checks(clauses,['Uses both null sides safely and emits only the designated port.','Selects all context from the present invoice, otherwise the bank.','VOID takes precedence over parsing, only for the exact spelling.','Validates complete signed-decimal text and bounds before conversion.','Prioritises text errors over invoice null and keeps repair quantities null.','Uses exact signed subtraction with zero only for absent sides.','Omits balanced matched pairs; retains one-sided zero rows with correct labels.','Sets repair/follow-up annotations and complete context without rewriting values.','Treats all first/final side combinations consistently without double routing.']),[('Must not dereference missing-side amounts as though both records were present.','Full outer joins create missing sides.'),('Must not parse VOID text, silently convert bad text to zero, or drop bank-only zero rows.','Those shortcuts violate precedence and completeness.')],fixture([a,b],{'0':exp0,'1':exp1}),settings={'joinKey':'$business_ref=$business_ref','joinType':'FULL_OUTER'},traps=['full outer null sides','parse exemption before validation','negative corrections']))
# T56 retained representative, expanded explicit edge clauses and fixture.
r=oldmeta('T56');fi=fieldsrec(r[0]);fo=fieldsrec(r[1]);old=OLD['T56']
clauses=[
'Supplier versions arrive sorted only by supplier_ref_no; every key must yield one real winning source row. A complete version has non-null, trimmed nonblank legal_nm, tax_country and payment_iban. Trimming classifies quality but does not edit the winner.',
'Complete versions outrank incomplete ones, regardless of recency. Within an equal quality rank, a real revision_at outranks null, even before the Unix epoch; later complete timestamps win. A date-only value is midnight and is never treated as missing.',
'When timestamps agree, including null against null, greater revision_no wins. An exact tie retains the earlier arriving row; revision numbers are non-null and duplicate values are legitimate.',
'Copy every field of the selected source version, including estimated_value, nullable context and the original whitespace in completeness fields. Do not construct a new version by combining fields from several candidates.',
'Count all candidates as versions_seen, including repeated versions. Set winner_complete from the selected record\'s quality; even an incomplete singleton is emitted with count one.',
'The first version of each key must become the candidate before comparing rank. Neither a default date nor a default revision number denotes a missing first record.',
'Groups are independent: winner eligibility, rank and count must not survive into the next key. Consecutive incomplete-only and null-timestamp-only groups still emit correctly; the final group is not forgotten.',
'Empty string and null both fail completeness while retaining their original representation in output. Text such as BAD:DATE in tax_country is still nonblank for this task; completeness is not semantic field validation. Do not parse completeness fields as dates or amounts.'
]
checks56=[(x['check'],x['rationale'],x['clauses']) for x in old['rubric']['required']]
# Eight clauses get one item each, avoiding stale six-clause references.
checks56=checks(clauses,['Emits one winner per supplier and classifies all three completeness fields without changing them.','Ranks completeness before real/null full timestamps including pre-epoch dates.','Handles null/null timestamp ties using descending revision_no and stable arrival tie.','Preserves all fields from exactly one selected source row.','Counts duplicates and sets winner_complete for every emitted key.','Uses effective first-candidate state rather than primitive default sentinels.','Resets group state with clean or an equivalent end-of-transform reset and emits final group.','Treats null/empty/blank completeness values as incomplete, but does not overvalidate nonblank text.'])
def supplier(k,n,**v):
 defaults=dict(supplier_ref_no=k,tenant_cd='T1',source_file_nm='sup.csv',received_at=D0,source_row_no=n,currency_cd='EUR',batch_ref='B',owner_team_cd=None,market_cd='',operator_note=None,external_trace_id='s'+str(n),unused_archive_label='x',legal_nm=' L ',tax_country='CZ',payment_iban=' IBAN ',revision_at=None,revision_no=1,estimated_value=None)
 defaults.update(v);return row(fi,**defaults)
s=[supplier('A',1,revision_at='1960-01-01 00:00:00'),supplier('A',2,revision_at='2026-01-01 00:00:00',payment_iban=''),supplier('A',3,revision_at='1960-01-01 00:00:00'),supplier('B',4,legal_nm=None,revision_no=1),supplier('B',5,legal_nm='',revision_no=2),supplier('B',6,legal_nm=' ',revision_no=2),supplier('C',7,tax_country='BAD:DATE'),supplier('D',8,revision_at=None),supplier('D',9,revision_at=None,revision_no=3)]
items.append(make('T56',5,old['component'],'Supplier master winner selection','The master loader needs one actual supplier version per key, including low-quality records for remediation. Timestamp order inside a group is unspecified; an upstream Sort supplies key ordering only.',clauses,[(r[0].attrib['name'],fi)],[(r[1].attrib['name'],fo)],old['reference'],checks56,[(x['check'],x['rationale']) for x in old['rubric']['forbidden']],fixture([s],{'0':[output(fo,s[0],winner_complete=True,versions_seen=3),output(fo,s[4],winner_complete=False,versions_seen=3),output(fo,s[6],winner_complete=True,versions_seen=1),output(fo,s[8],winner_complete=True,versions_seen=2)]}),settings={'groupKey':'supplier_ref_no'},change={'action':'kept','reason':'Best-reviewed quality/recency winner representative; adds explicit null-null and exact-tie fixture coverage.'},traps=['first candidate sentinel','null-null timestamp tiebreak','copy winner from append state']))
# T57 Rollup: per-record dispositions plus final winner stream.
fi=BASE+[F('receipt_id'),Q('amount'),F('voided','boolean',False)]
audit=fi+[F('disposition',nullable=False),F('winner_receipt'),F('rows_seen','integer',False)]
acc=BASE+[F('n','integer',False),F('accepted','integer',False),F('has_winner','boolean',False)]
clauses=[
'A receipt-control Rollup is grouped on business_ref after sorting only on that field. It has output 0 for one disposition per input receipt and output 1 for one final chosen receipt per group, provided the group has a candidate. Receipt order within a group is arrival order.',
'A usable identifier is non-null and nonblank after trimming. Use trimming only to test blankness; identifiers compare in their raw spelling, so R and space-R-space are distinct. Empty, null and whitespace-only identifiers get INVALID and never enter the duplicate register.',
'For a usable identifier the first arriving occurrence reserves that identifier, even when voided or amount is null/nonpositive. Later occurrences of that exact identifier get DUPLICATE before any amount or void checks and cannot become a winner.',
'A first occurrence is a candidate only when voided is false and amount is non-null and strictly positive. The earliest such candidate becomes the group winner; later candidates get ELIGIBLE but do not replace it. First occurrences that fail candidate quality get INELIGIBLE; the chosen occurrence gets WINNER.',
'Each output-0 record copies that input receipt unchanged, adds its disposition, and sets winner_receipt to the winner identifier known after considering that receipt, or null if none is known. rows_seen is the inclusive arrival count within its group.',
'At group completion output 1 copies the entire chosen receipt unchanged, uses disposition CHOSEN, winner_receipt equal to its own raw identifier, and rows_seen equal to the final group size. No winner means no output-1 record; the per-receipt dispositions must still be delivered.',
'Never send interim winner records to output 1. The two output streams have separate meanings and must not receive the same annotated record merely because both writers are connected. Duplicate inputs count separately in every arrival count.',
'Clear identifier membership and winner state between groups. A singleton with positive amount wins; an all-invalid or all-ineligible group has no chosen row. Preserve null amounts and unused archive context, and handle the first and final groups without losing their dispositions.',
'Identifier strings are not parsed: BAD:DATE is a valid nonblank identifier. A date at midnight is copied as supplied; an empty note remains empty while a null note stays null. The chosen row\'s context may differ from both the first and final group row.'
]
decl,save,emit=save_scalars(fi)
code=decl+'''string[] seen_ids;
string disposition;
string winner_id;
function void initGroup(ReceiptAcc acc) {clear(seen_ids);acc.n=0;acc.accepted=0;acc.has_winner=false;winner_id=null;}
function boolean updateGroup(ReceiptAcc acc) {
 acc.n++;
 if(isnull($in.0.receipt_id) || trim($in.0.receipt_id)=="") disposition="INVALID";
 else if(in($in.0.receipt_id,seen_ids)) disposition="DUPLICATE";
 else {append(seen_ids,$in.0.receipt_id);
  if($in.0.voided || isnull($in.0.amount) || $in.0.amount<=0D) disposition="INELIGIBLE";
  else {acc.accepted++;disposition="ELIGIBLE";if(!acc.has_winner) {'''+save+'''acc.has_winner=true;winner_id=$in.0.receipt_id;disposition="WINNER";}}
 }
 return true;
}
function integer updateTransform(integer counter,ReceiptAcc acc) {if(counter>0) return SKIP;$out.0.*=$in.0.*;$out.0.disposition=disposition;$out.0.winner_receipt=winner_id;$out.0.rows_seen=acc.n;return 0;}
function boolean finishGroup(ReceiptAcc acc) {return acc.has_winner;}
function integer transform(integer counter,ReceiptAcc acc) {if(counter>0) return SKIP;'''+emit.replace('$out.0.','$out.1.')+'''$out.1.disposition="CHOSEN";$out.1.winner_receipt=winner_id;$out.1.rows_seen=acc.n;return 1;}'''
s=[base(fi,'A',1,receipt_id=None,amount='5.00',voided=False),base(fi,'A',2,receipt_id='R',amount=None,voided=False),base(fi,'A',3,receipt_id='R',amount='10.00',voided=False),base(fi,'A',4,receipt_id=' R ',amount='2.00',voided=False),base(fi,'A',5,receipt_id='X',amount='4.00',voided=False),base(fi,'B',6,receipt_id='',amount='7.00',voided=False),base(fi,'B',7,receipt_id='V',amount='7.00',voided=True),base(fi,'C',8,receipt_id='BAD:DATE',amount='1.00',voided=False)]
manual=[('INVALID',None,1),('INELIGIBLE',None,2),('DUPLICATE',None,3),('WINNER',' R ',4),('ELIGIBLE',' R ',5),('INVALID',None,1),('INELIGIBLE',None,2),('WINNER','BAD:DATE',1)]
items.append(make('T57',5,'Rollup','Receipt decisions before the final chosen receipt','A point-of-sale repair pipeline requires an audit decision for every arriving receipt and a separate final winner stream. The Rollup owns both decisions: a duplicate can be rejected immediately, while the eventual chosen receipt must keep its own original context.',clauses,[('Receipt',fi)],[('ReceiptDecision',audit),('ReceiptDecision',audit)],code,checks(clauses,['Uses both per-record and final group emission without losing or multiplying rows.','Distinguishes raw IDs and excludes null/blank IDs from membership.','Registers first usable ID before eligibility and applies duplicate priority.','Selects earliest eligible receipt and annotates all dispositions correctly.','Copies each receipt to port 0 with inclusive count and current winner knowledge.','Copies actual chosen receipt to port 1 with final count; suppresses absent winners.','Keeps interim/final streams distinct and counts duplicate rows separately.','Resets group state and handles singleton/all-invalid/final groups.','Preserves raw strings, all source fields and date values on both streams.']),[('Must not emit only at group finish or send per-record rows to both outputs.','Every receipt needs exactly one disposition and only final winners need port 1.'),('Must not allow a repeated failed identifier to win later.','Identifier reservation precedes amount eligibility.')],fixture([s],{'0':[output(audit,x,disposition=d,winner_receipt=w,rows_seen=n) for x,(d,w,n) in zip(s,manual)],'1':[output(audit,s[3],disposition='CHOSEN',winner_receipt=' R ',rows_seen=5),output(audit,s[7],disposition='CHOSEN',winner_receipt='BAD:DATE',rows_seen=1)]}),settings={'groupKey':'business_ref'},acc=('ReceiptAcc',acc),traps=['per-record and group output','reserve failed IDs','winner context differs from final input']))
# T58 list evidence: retract prior candidates, allow later additions.
fi=BASE+[F('slot_id'),F('operation'),F('units_txt'),DATE('observed_at'),Q('unit_cost')]
fo=BASE+[F('chosen_slot'),DATE('chosen_at'),Q('chosen_units'),Q('chosen_cost'),F('surviving_slots',nullable=False),F('rows_seen','integer',False)]
clauses=[
'The inventory Denormalizer groups by business_ref on a stream sorted by that field only. Produce one survivor summary for every warehouse key in group order, including an empty survivor group. The context fields come from the first source record.',
'A usable slot_id is non-null and nonblank after trimming, but comparisons and evidence retain its raw spelling. Ignore operations on unusable identifiers while still counting their rows. Unknown operations, including null and differently cased spelling, are ignored.',
'An operation exactly REMOVE retracts every earlier retained ADD with that raw slot_id. A REMOVE never prevents a later ADD of the same slot. Removing an unknown slot is harmless. Remaining evidence keeps the arrival order of surviving additions, including repeated additions.',
'An operation exactly ADD is retained only when units_txt, after trimming, matches ASCII digits with an optional decimal part of one or two digits, at most nine integer digits, and the parsed value is strictly positive. Signs, exponent, blank, null and malformed text are ignored without a parsing failure; other rows in that key still survive.',
'Choose among surviving additions by greatest chosen_units first. If units tie, prefer a non-null observed_at over null, then the latest complete timestamp. A remaining tie retains the earlier addition. Dates before the epoch and date-only midnight are legitimate times.',
'The summary chosen_slot, chosen_at, chosen_units and chosen_cost all come from the same chosen addition; chosen_cost may be null or negative and does not affect ranking. A warehouse with no survivors sets those four fields to null.',
'surviving_slots is the raw slot identifiers of retained additions in their current arrival order, joined with a comma. There is no trailing comma, and no survivors means an empty string. It is evidence of every survivor, not just the selected winner.',
'rows_seen counts every input including ignored malformed additions and repeated removals. Copy every remaining context field from the saved first record, including its nullable context_value and unused_archive_label; do not use the last addition\'s context.',
'Each new warehouse starts with empty retained history and fresh count. Do not let a prior removal or candidate influence the next group. The first warehouse, an empty middle warehouse, a final singleton and duplicate slot identifiers must all satisfy the same rules.'
]
decl,save,emit=save_scalars(BASE,'first')
code=decl+'''string[] slots;
decimal[] units;
date[] times;
decimal[] costs;
integer n;
function integer append() {
 if(n==0) {'''+save+'''}n++;
 string id=$in.0.slot_id;
 if(isnull(id) || trim(id)=="") return OK;
 if($in.0.operation=="REMOVE") {for(integer j=length(slots)-1;j>=0;j--) {if(slots[j]==id) {remove(slots,j);remove(units,j);remove(times,j);remove(costs,j);}}}
 else if($in.0.operation=="ADD") {string text=isnull($in.0.units_txt) ? "" : trim($in.0.units_txt);if(text ~= "[0-9]{1,9}(\\\\.[0-9]{1,2})?") {decimal q=str2decimal(text);if(q>0D) {append(slots,id);append(units,q);append(times,$in.0.observed_at);append(costs,$in.0.unit_cost);}}}
 return OK;
}
function integer transform() {
 integer pick=-1;
 for(integer j=0;j<length(slots);j++) {boolean better=pick<0;if(pick>=0) {if(units[j]>units[pick]) better=true;else if(units[j]==units[pick]) {if(!isnull(times[j]) && isnull(times[pick])) better=true;else if(!isnull(times[j]) && !isnull(times[pick]) && times[j]>times[pick]) better=true;}}if(better) pick=j;}
 '''+emit+'''$out.0.rows_seen=n;$out.0.surviving_slots=join(",",slots);
 $out.0.chosen_slot=pick<0 ? null : slots[pick];$out.0.chosen_at=pick<0 ? null : times[pick];$out.0.chosen_units=pick<0 ? null : units[pick];$out.0.chosen_cost=pick<0 ? null : costs[pick];return OK;
}
function void clean() {n=0;clear(slots);clear(units);clear(times);clear(costs);}'''
s=[base(fi,'A',1,slot_id='S',operation='ADD',units_txt='8',observed_at=None,unit_cost='1.00'),base(fi,'A',2,slot_id='S',operation='ADD',units_txt='9',observed_at=D0,unit_cost='2.00'),base(fi,'A',3,slot_id='S',operation='REMOVE'),base(fi,'A',4,slot_id='X',operation='ADD',units_txt='bad:date'),base(fi,'A',5,slot_id='S',operation='ADD',units_txt='3.50',observed_at='1960-01-01 00:00:00',unit_cost=None),base(fi,'A',6,slot_id='T',operation='ADD',units_txt='3.50',observed_at=None,unit_cost='-1.00'),base(fi,'A',7,slot_id='T',operation='ADD',units_txt='3.50',observed_at=D0,unit_cost='4.00'),base(fi,'B',8,slot_id=None,operation='ADD',units_txt='4'),base(fi,'B',9,slot_id='S',operation='REMOVE'),base(fi,'C',10,slot_id='S',operation='ADD',units_txt='1',observed_at=D0,unit_cost='0.00')]
items.append(make('T58',5,'Denormalizer','Inventory survivor evidence after retractions','Warehouse messages can retract an earlier candidate and then add it again. A single running best value cannot answer the final request because the previous best may disappear. The downstream warehouse audit needs both the winner and the complete surviving evidence.',clauses,[('StockMessage',fi)],[('StockSummary',fo)],code,checks(clauses,['Emits one summary per group and saves first context.','Guards unusable IDs and exact operation spelling without dropping row counts.','Retracts all prior same-ID candidates while allowing later re-additions.','Rejects invalid/nonpositive text safely with complete bounded grammar.','Ranks final survivors by units, timestamp presence/full recency, stable arrival.','Copies all four winner fields from one candidate or sets all four null.','Builds ordered surviving evidence retaining duplicate additions.','Counts every arrival and preserves every first-row context field.','Resets list state/count and handles empty, singleton and terminal groups.']),[('Must not keep only a running winner, erase future re-additions, or deduplicate evidence.','Retractions require retained survivor history.'),('Must not parse ignored malformed units or index a winner when survivors are empty.','Those inputs require a defined nonthrowing summary.')],fixture([s],{'0':[output(fo,s[0],chosen_slot='T',chosen_at=D0,chosen_units='3.50',chosen_cost='4.00',surviving_slots='S,T,T',rows_seen=7),output(fo,s[7],chosen_slot=None,chosen_at=None,chosen_units=None,chosen_cost=None,surviving_slots='',rows_seen=2),output(fo,s[9],chosen_slot='S',chosen_at=D0,chosen_units='1.00',chosen_cost='0.00',surviving_slots='S',rows_seen=1)]}),settings={'groupKey':'business_ref'},traps=['parallel list state','retraction removes prior winner','empty survivor output']))
# T59 retained account per-event SCD representative.
r=oldmeta('T59');fi=fieldsrec(r[0]);fo=fieldsrec(r[1]);old=OLD['T59']
clauses=[
'A resolved account event arrives with optional prior current version values. previous_sk null means a new account; otherwise previous_from is non-null. Compare the incoming risk_class and contract_value with previous_risk_class and previous_value. row_kind is merely a label, never a route.',
'An existing version is unchanged only if both tracked attributes agree under null-safe equality. Null agrees with null but differs from empty text or numeric zero. Unchanged existing events emit no records and consume no surrogate key.',
'A changed existing account closes on output 0: version_sk is previous_sk, valid_from is previous_from, valid_to is event_at, and is_current is false. The closing risk_class and contract_value must be the prior attribute values, not the incoming replacements.',
'Every new account and changed account opens on output 1 with incoming attributes, valid_from event_at, null valid_to and is_current true. Obtain its long surrogate from the graph-managed DimKeys sequence, initially 900000 with step one.',
'Consume precisely one DimKeys value per opening version. A closing record, an unchanged record and any inspection of input placeholders must not allocate another key; never reset the sequence in CTL.',
'Dates are prevalidated UTC. An event with a prior version is strictly later than previous_from. Windows are half-open: the old valid_to equals the new valid_from exactly. Midnight is valid; do not create a second/day gap.',
'Changed existing accounts require both writers, while a new account requires only the insert writer. Repeated account keys are allowed because the resolver supplies the right prior version separately for each event; the component must keep arrival order without its own reconciliation buffer.',
'Copy every other common source field to each emitted record. Overwrite incoming version_sk, valid_from, valid_to and is_current placeholders in all cases. Preserve nullable audit context, unused_archive_label, date values and original spellings.',
'The first event may be a new account whose attributes are both null: it still opens. The final event may be a null-to-empty change: it still closes and opens. Text that resembles a malformed date in a note is copied without parsing; exact duplicate unchanged events produce no additional history.'
]
checks59=checks(clauses,['Uses previous_sk existence and the two exact previous attribute counterparts.','Skips unchanged null-safe states before key allocation.','Restores all closing version dates, key and old attributes on port 0.','Builds the incoming opening state on port 1 with a long DimKeys value.','Allocates exactly once per opening and never for close/unchanged.','Uses exact UTC half-open boundary including midnight.','Routes changed existing to both outputs, new to port 1, preserving arrival order.','Copies all remaining common fields and overwrites all placeholders.','Handles first all-null new state, duplicate unchanged and final null-to-empty change.'])
def account(k,n,**v):
 d=dict(account_ref_no=k,tenant_cd='T1',source_file_nm='accounts.csv',received_at=D0,source_row_no=n,currency_cd='EUR',batch_ref='B',owner_team_cd=None,market_cd='',operator_note='BAD:DATE' if n==1 else None,external_trace_id='a'+str(n),unused_archive_label='',risk_class=None,version_sk=0,valid_from=D0,valid_to=D0,is_current=False,row_kind='IGNORED',event_at='2026-01-02 00:00:00',contract_value=None,previous_sk=None,previous_from=None,previous_risk_class=None,previous_value=None);d.update(v);return row(fi,**d)
s=[account('A',1),account('A',2,previous_sk=900000,previous_from='2026-01-02 00:00:00',event_at='2026-01-03 00:00:00'),account('B',3,previous_sk=7,previous_from=D0,previous_risk_class='LOW',risk_class='HIGH',contract_value='2.00',previous_value='2.00'),account('C',4,risk_class='',contract_value='0.00'),account('D',5,previous_sk=8,previous_from=D0,previous_value='0.00',contract_value='0.00'),account('D',6,previous_sk=8,previous_from=D0,previous_value='0.00',contract_value=None),account('E',7,previous_sk=9,previous_from=D0,previous_risk_class='LOW',risk_class='LOW'),account('F',8,previous_sk=10,previous_from=D0,risk_class='')]
opens=[(0,900000),(2,900001),(3,900002),(5,900003),(7,900004)];closes=[(2,7,'LOW','2.00'),(5,8,None,'0.00'),(7,10,None,None)]
items.append(make('T59',6,old['component'],'Account dimension versioning','A history resolver attaches prior account values to each event before this Reformat. Two database writers accept closing updates and inserted versions. DimKeys is a long sequence owned by the graph, starting at 900000 and incrementing by one.',clauses,[(r[0].attrib['name'],fi)],[(r[1].attrib['name'],fo),(r[2].attrib['name'],fo)],old['reference'],checks59,[(x['check'],x['rationale']) for x in old['rubric']['forbidden']],fixture([s],{'0':[output(fo,s[i],version_sk=k,valid_from=s[i]['previous_from'],valid_to=s[i]['event_at'],is_current=False,risk_class=t,contract_value=v) for i,k,t,v in closes],'1':[output(fo,s[i],version_sk=k,valid_from=s[i]['event_at'],valid_to=None,is_current=True) for i,k in opens]}),resources={'sequences':[{'id':'DimKeys','name':'DimKeys','type':'long','start':900000,'step':1}]},change={'action':'kept','reason':'Reviewed per-event account SCD representative; broadens first all-null and final null-to-empty fixture.'},traps=['new all-null opens','one vs both ports','typed sequence once']))
# T60 Normalizer prepares close/open/audit expansion per request.
fi=BASE+[F('request_kind',nullable=False),F('new_rate_txt'),F('audit_requested','boolean',False),DATE('event_at',False),F('previous_sk','long'),DATE('previous_from'),Q('previous_rate')]
fo=BASE+[F('version_sk','long'),DATE('valid_from'),DATE('valid_to'),F('is_current','boolean'),Q('rate'),F('record_kind',nullable=False),F('audit_note',nullable=False)]
clauses=[
'This Normalizer receives pre-resolved tariff requests; its output 0 feeds the version writer and output 1 feeds an audit queue. A request_kind of CANCEL withdraws a current tariff; every other spelling requests the incoming tariff. previous_sk null means there is no current version.',
'For a tariff request, null or trimmed empty new_rate_txt means an unpriced tariff with rate null. Otherwise accept only ASCII digits, at most eight integer digits, optionally followed by one or two decimal digits. Signs, exponent, commas and malformed text produce one audit ERROR with audit_note BAD_RATE and no version records.',
'CANCEL takes precedence over rate validation. Ignore new_rate_txt completely on cancellation, even if malformed. If a previous version exists, close it; cancellation always creates an audit CANCELLED record, regardless of audit_requested, and never consumes a sequence value.',
'An existing requested tariff whose parsed rate equals previous_rate under null-safe equality does not create versions. If audit_requested is true it creates one audit UNCHANGED record; otherwise it is silent. A new tariff opens even if its rate is null.',
'A replacement emits two version records in order: CLOSE of the prior version followed by OPEN of the new one. A new tariff emits only OPEN. A cancellation emits only CLOSE when applicable. All these version records go to port 0; their record_kind supplies the operation.',
'CLOSE uses the previous surrogate, previous_from and previous_rate, with valid_to event_at and is_current false. OPEN gets one long value from graph sequence PriceKeys (starts 1000, step one), valid_from event_at, valid_to null and is_current true. UTC dates are prevalidated and every existing-version event is after previous_from; boundaries are half-open with no time subtraction.',
'For a changed or new tariff with audit_requested true, append an audit REPRICED record after its version records. It carries the new version fields. CANCELLED and UNCHANGED audit records carry the previous version fields, with valid_to event_at for CANCELLED and null for UNCHANGED. A missing previous version gives null version fields on CANCELLED; ERROR likewise has all version fields null.',
'Every emitted row copies all base context from that request, including unused_archive_label and nullable context_value. audit_note is empty except for BAD_RATE. Audit rows are port 1 only; never broadcast a version row to the audit writer or obtain another key merely for the audit copy.',
'Preparation is independent per request. Preserve order among expansions of one request and among requests within each output. A malformed middle request, a silent unchanged request, a new null-rate first request and a cancellation at the final request must not reuse an earlier prepared count, key or rate.'
]
code='''integer n;
boolean exists;
boolean cancel;
boolean changed;
boolean bad;
decimal parsed_rate;
long new_key;
function integer count() {
 n=0;exists=!isnull($in.0.previous_sk);cancel=$in.0.request_kind=="CANCEL";changed=false;bad=false;parsed_rate=null;new_key=null;
 if(cancel) {n=exists ? 2 : 1;return n;}
 string text=isnull($in.0.new_rate_txt) ? "" : trim($in.0.new_rate_txt);
 if(text!="") {if(!(text ~= "[0-9]{1,8}(\\\\.[0-9]{1,2})?")) {bad=true;return 1;}parsed_rate=str2decimal(text);}
 changed=!exists || parsed_rate!=$in.0.previous_rate;
 if(!changed) return $in.0.audit_requested ? 1 : 0;
 new_key=sequence(PriceKeys,long).next();n=(exists ? 2 : 1)+($in.0.audit_requested ? 1 : 0);return n;
}
function integer transform(integer idx) {
 $out.0.*=$in.0.*;$out.1.*=$in.0.*;
 $out.0.audit_note="";$out.1.audit_note="";
 if(bad) {$out.1.version_sk=null;$out.1.valid_from=null;$out.1.valid_to=null;$out.1.is_current=null;$out.1.rate=null;$out.1.record_kind="ERROR";$out.1.audit_note="BAD_RATE";return 1;}
 if(cancel || !changed) {
  boolean closing=cancel && exists && idx==0;
  if(closing) {$out.0.version_sk=$in.0.previous_sk;$out.0.valid_from=$in.0.previous_from;$out.0.valid_to=$in.0.event_at;$out.0.is_current=false;$out.0.rate=$in.0.previous_rate;$out.0.record_kind="CLOSE";return 0;}
  $out.1.version_sk=$in.0.previous_sk;$out.1.valid_from=exists ? $in.0.previous_from : null;$out.1.valid_to=(cancel && exists) ? $in.0.event_at : null;$out.1.is_current=exists ? !cancel : null;$out.1.rate=exists ? $in.0.previous_rate : null;$out.1.record_kind=cancel ? "CANCELLED" : "UNCHANGED";return 1;
 }
 if(exists && idx==0) {$out.0.version_sk=$in.0.previous_sk;$out.0.valid_from=$in.0.previous_from;$out.0.valid_to=$in.0.event_at;$out.0.is_current=false;$out.0.rate=$in.0.previous_rate;$out.0.record_kind="CLOSE";return 0;}
 integer open_idx=exists ? 1 : 0;
 if(idx==open_idx) {$out.0.version_sk=new_key;$out.0.valid_from=$in.0.event_at;$out.0.valid_to=null;$out.0.is_current=true;$out.0.rate=parsed_rate;$out.0.record_kind="OPEN";return 0;}
 $out.1.version_sk=new_key;$out.1.valid_from=$in.0.event_at;$out.1.valid_to=null;$out.1.is_current=true;$out.1.rate=parsed_rate;$out.1.record_kind="REPRICED";return 1;
}
function void clean() {n=0;parsed_rate=null;new_key=null;}'''
def req(k,n,**v):
 d=dict(request_kind='SET',audit_requested=False,event_at='2026-01-02 00:00:00');d.update(v);return base(fi,k,n,**d)
s=[req('A',1,new_rate_txt=None),req('B',2,new_rate_txt='1.25',previous_sk=7,previous_from=D0,previous_rate='1.25'),req('C',3,new_rate_txt='2',previous_sk=8,previous_from=D0,previous_rate='1.00',audit_requested=True),req('D',4,request_kind='CANCEL',new_rate_txt='BAD:DATE',previous_sk=9,previous_from=D0,previous_rate='3.00'),req('E',5,request_kind='CANCEL',new_rate_txt='1e2'),req('F',6,new_rate_txt='',previous_sk=10,previous_from=D0,previous_rate=None,audit_requested=True),req('G',7,new_rate_txt='1e2'),req('H',8,new_rate_txt='0',previous_sk=11,previous_from=D0,previous_rate=None),req('I',9,request_kind='CANCEL',new_rate_txt=None,previous_sk=12,previous_from=D0,previous_rate=None)]
def version(i,kind,k,rate,frm,to,current,note=''):return output(fo,s[i],version_sk=k,valid_from=frm,valid_to=to,is_current=current,rate=rate,record_kind=kind,audit_note=note)
exp0=[version(0,'OPEN',1000,None,s[0]['event_at'],None,True),version(2,'CLOSE',8,'1.00',D0,s[2]['event_at'],False),version(2,'OPEN',1001,'2.00',s[2]['event_at'],None,True),version(3,'CLOSE',9,'3.00',D0,s[3]['event_at'],False),version(7,'CLOSE',11,None,D0,s[7]['event_at'],False),version(7,'OPEN',1002,'0.00',s[7]['event_at'],None,True),version(8,'CLOSE',12,None,D0,s[8]['event_at'],False)]
exp1=[version(2,'REPRICED',1001,'2.00',s[2]['event_at'],None,True),version(3,'CANCELLED',9,'3.00',D0,s[3]['event_at'],False),version(4,'CANCELLED',None,None,None,None,None),version(5,'UNCHANGED',10,None,D0,None,True),version(6,'ERROR',None,None,None,None,None,'BAD_RATE'),version(8,'CANCELLED',12,None,D0,s[8]['event_at'],False)]
items.append(make('T60',6,'Normalizer','Tariff version operations and optional audits','Tariff maintenance expands a resolved pricing request into ordered database operations and, where requested, a separate audit record. PriceKeys is a graph-managed long sequence beginning at 1000 and stepping by one. The Normalizer handles every expansion itself.',clauses,[('TariffRequest',fi)],[('TariffOperation',fo),('TariffOperation',fo)],code,checks(clauses,['Recognises CANCEL independently of previous presence and uses separate writer destinations.','Validates bounded rate text, preserves blank/null unpriced tariff, and emits one ERROR safely.','Cancellation bypasses malformed rate and allocates no new key.','Uses null-safe rate equality, optional unchanged audit, and opens new null-priced tariffs.','Expands replacement as CLOSE then OPEN and handles single new/cancel cases.','Uses previous/new version fields and exactly one long PriceKeys value per opening.','Builds REPRICED/CANCELLED/UNCHANGED/ERROR audit version fields as specified.','Copies all context and annotations without broadcasting or reallocating audit keys.','Resets preparation and preserves expansion/input order across silent and failed requests.']),[('Must not return the same count for every request, or allocate one sequence value per emitted row.','Version and audit expansion counts vary.'),('Must not parse CANCEL garbage or treat blank requested rate as malformed.','Cancellation and unpriced tariffs have explicit safe semantics.')],fixture([s],{'0':exp0,'1':exp1}),resources={'sequences':[{'id':'PriceKeys','name':'PriceKeys','type':'long','start':1000,'step':1}]},traps=['Normalizer close/open/audit expansion','parse cancellation exemption','sequence once per prepared opening']))
# T61: state carried across events, with seed used only on first row per key.
fi=BASE+[F('region_cd'),Q('service_fee'),DATE('effective_at',False),F('seed_sk','long'),DATE('seed_from'),F('seed_region'),Q('seed_fee')]
fo=BASE+[F('region_cd'),Q('service_fee'),F('version_sk','long',False),DATE('valid_from',False),DATE('valid_to'),F('is_current','boolean',False)]
clauses=[
'This Reformat receives contiguous runs of business_ref in ascending key order and effective_at order. Output 0 updates closing versions and output 1 inserts openings. The empty reference string is a legitimate key; it must not be mistaken for uninitialised state.',
'Only the first row of a key may use seed_sk, seed_from, seed_region and seed_fee. A non-null seed_sk introduces a current historical version; seed_from is then non-null. Subsequent seed fields can be stale and must be ignored: compare against the current state accepted by this component.',
'The tracked state is the exact nullable region_cd and service_fee pair. Null equals null, empty region differs from null, and numeric zero differs from null. An unchanged row emits nothing, does not advance GeoKeys, and does not replace the saved current context or starting date.',
'If no current version exists, open the incoming state even when both attributes are null. Every opening receives one long graph-managed GeoKeys value, initially 3000 with step one, valid_from effective_at, null valid_to and is_current true.',
'For a changed existing state, first build a closing record on output 0 using its current surrogate, saved starting date and saved tracked attributes, valid_to equal to the incoming effective_at and is_current false. Send the opening on output 1. Exactly one sequence value is used for this pair.',
'Closing context for a seeded version comes from the first row that introduced that seed. Closing context for a component-created version comes from the row that opened it. Openings always use the current input context. Preserve every context field including notes and unused_archive_label.',
'When an opening succeeds, remember its full context, attributes, assigned key and starting date for later events. A later unchanged row must not erase that stored source. Reset the whole current-state interpretation when business_ref changes, even following a silent first row.',
'All dates are prevalidated UTC. Changed events are strictly later than the accepted current start; duplicate unchanged events may have the same time. Half-open windows meet at exactly effective_at, including midnight. Date-looking notes such as 2025-02-30 remain unparsed text.',
'Keep arrival order within each destination, emitting new keys only to port 1 and changes to both ports. Handle the first empty-string key, exact duplicate events, null-to-empty attribute transitions, singleton keys, and the final seeded key without dropping or broadcasting records.'
]
decl,save,emit=save_scalars(BASE,'current')
code=decl+'''boolean have_key;
string current_business_key;
boolean have_version;
long sk;
date from_at;
string region;
decimal fee;
function integer transform() {
 if(!have_key || current_business_key!=$in.0.business_ref) {have_key=true;current_business_key=$in.0.business_ref;have_version=!isnull($in.0.seed_sk);sk=$in.0.seed_sk;from_at=$in.0.seed_from;region=$in.0.seed_region;fee=$in.0.seed_fee;'''+save+'''}
 boolean changed=$in.0.region_cd!=region || $in.0.service_fee!=fee;
 if(have_version && !changed) return SKIP;
 boolean close=have_version;
 if(close) {'''+emit+'''$out.0.region_cd=region;$out.0.service_fee=fee;$out.0.version_sk=sk;$out.0.valid_from=from_at;$out.0.valid_to=$in.0.effective_at;$out.0.is_current=false;}
 long next_key=sequence(GeoKeys,long).next();
 $out.1.*=$in.0.*;$out.1.version_sk=next_key;$out.1.valid_from=$in.0.effective_at;$out.1.valid_to=null;$out.1.is_current=true;
 '''+save+'''region=$in.0.region_cd;fee=$in.0.service_fee;sk=next_key;from_at=$in.0.effective_at;have_version=true;
 if(close) return ALL;return 1;
}'''
def geo(k,n,**v):
 d=dict(effective_at=f'2026-01-{n+1:02d} 00:00:00');d.update(v);return base(fi,k,n,**d)
s=[geo('',1,region_cd=None,service_fee=None),geo('',2,region_cd=None,service_fee=None,seed_sk=999,seed_from=D0,seed_region='STALE',seed_fee='9.00'),geo('',3,region_cd='',service_fee=None),geo('A',4,region_cd='E',service_fee='5.00',seed_sk=7,seed_from=D0,seed_region='E',seed_fee='5.00'),geo('A',5,region_cd='F',service_fee='5.00'),geo('A',6,region_cd='F',service_fee=None),geo('B',7,region_cd='ZZ',service_fee='0.00'),geo('B',8,region_cd='ZZ',service_fee='0.00'),geo('C',9,region_cd='Z',service_fee='2.00',seed_sk=8,seed_from=D0,seed_region='Z',seed_fee='1.00')]
openpairs=[(0,3000),(2,3001),(4,3002),(5,3003),(6,3004),(8,3005)]
closemanual=[(s[0],3000,s[0]['effective_at'],s[2]['effective_at'],None,None),(s[3],7,D0,s[4]['effective_at'],'E','5.00'),(s[4],3002,s[4]['effective_at'],s[5]['effective_at'],'F','5.00'),(s[8],8,D0,s[8]['effective_at'],'Z','1.00')]
items.append(make('T61',6,'Reformat','Service-region history carried through consecutive events','The geographic service feed provides a seed only when entering a new reference run. Several later events for that reference may change the state again. This Reformat maintains the accepted state and uses GeoKeys, a graph-managed long sequence starting at 3000 and stepping by one.',clauses,[('RegionEvent',fi)],[('RegionVersion',fo),('RegionVersion',fo)],code,checks(clauses,['Uses explicit key-presence state and handles a legitimate empty-string first key.','Consults seeds only when entering a key and ignores later stale seed data.','Uses exact null-safe pair equality and leaves state/context/key allocation untouched for unchanged rows.','Opens missing versions, including all-null states, using one long GeoKeys value.','Closes prior accepted fields and opens replacement with correct ports and one allocation.','Uses seeded-first or saved-opening context for closes and input context for opens.','Remembers opening state and resets fully per key without losing silent seeded initialization.','Uses exact UTC half-open boundaries without parsing incidental notes.','Preserves destination order and handles duplicates, singleton/final keys and null-to-empty changes.']),[('Must not compare every event to its own seed or use a default empty string/date as a first-key sentinel.','The accepted state and legitimate empty key require explicit presence.'),('Must not replace current context on unchanged events or put incoming attributes on the close.','Historical context comes from the accepted version.')],fixture([s],{'0':[output(fo,src,version_sk=k,valid_from=frm,valid_to=to,is_current=False,region_cd=rg,service_fee=fee) for src,k,frm,to,rg,fee in closemanual],'1':[output(fo,s[i],version_sk=k,valid_from=s[i]['effective_at'],valid_to=None,is_current=True) for i,k in openpairs]}),resources={'sequences':[{'id':'GeoKeys','name':'GeoKeys','type':'long','start':3000,'step':1}]},traps=['first key empty sentinel','ignore stale subsequent seeds','close saved accepted context']))
# T62: keep claim monthly report but couple override parsing, waiver and previous status.
r=oldmeta('T62');fi=fieldsrec(r[0])+[F('amount_override_txt'),F('late_waived','boolean',False)];fo=fieldsrec(r[1])+[F('bad_amount_rows','integer',False),F('reopened_rows','integer',False)];acc=fieldsrec(r[2])+[F('bad_amounts','integer',False),F('reopened','integer',False),F('previous_seen','boolean',False),F('previous_status')]
clauses=[
'Claims arrive at a Rollup sorted and grouped by group_key, a key that already combines tenant, claim unit and UTC calendar month. Every group is nonempty and requires one monthly summary on output 0. Typed dates follow a UTC business calendar; the runtime default timezone may differ.',
'period_label is yyyy-MM using the group month. Preserve every base context field from the first claim event, including claim_ref_no, source_row_no and operator_note, which may vary later in the group. The unused_archive_label is still part of that saved context.',
'An amount_override_txt that is null means use net_amount, including its possible null. A non-null override must trim to a complete ASCII decimal with an optional minus sign, one to ten integer digits, and an optional decimal point followed by one or two fractional digits; leading plus is invalid; null is the only fallback trigger. Empty, whitespace, exponent, impossible-date text and malformed overrides increment bad_amount_rows and contribute no amount, even if net_amount was usable.',
'rows_seen counts all events. For usable effective amounts, paid_total sums status_cd exactly PAID and pending_total sums exactly PENDING. Unknown, null, empty and differently cased statuses contribute to neither bucket. Negative amounts reduce their bucket; a missing amount contributes nothing.',
'billable_average uses usable non-null effective amounts on billable true events only. Its divisor counts these amounts, including zero and negative ones, independently of their payment status. Round the decimal mean half-up to two places; no eligible amounts means null rather than zero.',
'A late event has non-null delay_days greater than two and late_waived false. A waived event is not late even when the delay is large. late_percent is 100 times the late count divided by every rows_seen, decimal division rounded half-up to two places. A bad amount still participates in delay classification and the denominator.',
'reopened_rows counts adjacent arrivals where the immediately preceding status was exactly PAID and the current status is exactly PENDING. Amount validity, billability and waiver do not affect this transition count. The first event of each group has no predecessor; null/empty status does not mean PAID.',
'Accumulate each event exactly once and emit a summary only at group end. Reset counts, sums, predecessor presence/status and saved first context between groups. All-null amount groups still have row counts and percentages, and must not inherit a predecessor from the previous group.',
'Conserve repeated inputs as separate arrivals. Handle a singleton group, a 1-in-3 late fraction, an invalid override in the middle, a first and final group, and a date without time. Copy null and empty context verbatim rather than parsing date-looking notes or silently discarding a failed amount event.'
]
context=fieldsrec(r[0])[:12];decl,save,emit=save_scalars(context,'first')
code=decl+'''function void initGroup(ReportAcc acc) {'''+save+'''acc.n=0;acc.late=0;acc.eligible=0;acc.paid=0D;acc.pending=0D;acc.eligible_total=0D;acc.bad_amounts=0;acc.reopened=0;acc.previous_seen=false;acc.previous_status=null;}
function boolean updateGroup(ReportAcc acc) {
 acc.n++;
 if(acc.previous_seen && acc.previous_status=="PAID" && $in.0.status_cd=="PENDING") acc.reopened++;
 acc.previous_seen=true;acc.previous_status=$in.0.status_cd;
 if(!isnull($in.0.delay_days) && $in.0.delay_days>2 && !$in.0.late_waived) acc.late++;
 decimal amount=$in.0.net_amount;boolean valid=true;
 if(!isnull($in.0.amount_override_txt)) {string txt=trim($in.0.amount_override_txt);if(!(txt ~= "-?[0-9]{1,10}(\\\\.[0-9]{1,2})?")) {acc.bad_amounts++;valid=false;}else amount=str2decimal(txt);}
 if(valid && !isnull(amount)) {if($in.0.status_cd=="PAID") acc.paid+=amount;if($in.0.status_cd=="PENDING") acc.pending+=amount;if($in.0.billable) {acc.eligible++;acc.eligible_total+=amount;}}
 return false;
}
function integer updateTransform(integer counter,ReportAcc acc) {return SKIP;}
function boolean finishGroup(ReportAcc acc) {return true;}
function integer transform(integer counter,ReportAcc acc) {if(counter>0) return SKIP;'''+emit+'''$out.0.group_key=$in.0.group_key;$out.0.period_label=date2str($in.0.occurred_at,"yyyy-MM","en.US","UTC");$out.0.rows_seen=acc.n;$out.0.paid_total=acc.paid;$out.0.pending_total=acc.pending;$out.0.billable_average=acc.eligible==0 ? null : round(acc.eligible_total/acc.eligible,2);$out.0.late_percent=round(100D*acc.late/acc.n,2);$out.0.bad_amount_rows=acc.bad_amounts;$out.0.reopened_rows=acc.reopened;return OK;}'''
def claim(k,n,**v):
 d=dict(claim_ref_no='claim-'+str(n),tenant_cd='T1',source_file_nm='claim.csv',received_at=D0,source_row_no=n,currency_cd='EUR',batch_ref='B',owner_team_cd=None,market_cd='',operator_note='2025-02-30' if n==1 else None,external_trace_id='c'+str(n),unused_archive_label='first-'+str(n),group_key=k,occurred_at=D0,net_amount=None,status_cd=None,billable=True,delay_days=None,amount_override_txt=None,late_waived=False);d.update(v);return row(fi,**d)
s=[claim('A',1,net_amount='100.00',status_cd='PAID',delay_days=4,late_waived=True),claim('A',2,net_amount='200.00',status_cd='PENDING',amount_override_txt='1.005',delay_days=4),claim('A',3,net_amount='999.00',status_cd='PENDING',amount_override_txt=' -2.50 ',delay_days=4),claim('A',4,net_amount='1.00',status_cd='PAID',amount_override_txt=''),claim('A',5,status_cd='PENDING'),claim('A',6,net_amount='0.01',status_cd='PAID',billable=False,delay_days=0),claim('B',7,status_cd='PENDING'),claim('B',8,net_amount='5.00',status_cd='PAID',amount_override_txt='2025-02-30'),claim('B',9,status_cd='PENDING',amount_override_txt='1e2'),claim('C',10,net_amount='0.00',status_cd='paid'),claim('D',11,net_amount='0.01',status_cd=None),claim('D',12,net_amount='0.02',status_cd='')]
s.extend([dict(s[10]),dict(s[11])])
summary=[(0,6,'100.01','-2.50','48.75','33.33',2,2),(6,3,'0.00','0.00',None,'0.00',2,1),(9,1,'0.00','0.00','0.00','0.00',0,0),(10,4,'0.00','0.00','0.02','0.00',0,0)]
items.append(make('T62',7,'Rollup','Claim monthly report with override and reopening controls','The claims reporting writer still needs the monthly business buckets and first-event context. New correction feeds supply a textual override and late waivers, while operations also wants to know whether a paid claim was immediately reopened. These decisions belong in this one Rollup.',clauses,[(r[0].attrib['name'],fi)],[(r[1].attrib['name'],fo)],code,checks(clauses,['Uses grouped nonempty month summaries and the graph UTC assumptions.','Computes yyyy-MM and saves/copies every first context field.','Distinguishes null fallback from invalid non-null overrides and counts bad amounts safely.','Counts all rows and sums exact status buckets from valid effective decimal amounts.','Uses the independently eligible billable divisor, null zero-population result and half-up rounding.','Applies late waiver and decimal percentage over all arrivals including amount failures.','Counts only adjacent PAID-to-PENDING transitions using effective predecessor presence.','Implements one final summary with all lifecycle functions and complete group reset.','Preserves duplicates, null/empty context, singleton/final/all-null groups and midpoint rounding.']),[('Must not fall back to net_amount for an empty or malformed non-null override.','Null alone selects fallback.'),('Must not leak predecessor across groups, count only valid-amount rows in late denominator, or use integer percentage division.','Population and transition contracts are independent of amount validity.')],fixture([s],{'0':[output(fo,s[i],period_label='2026-01',rows_seen=n,paid_total=p,pending_total=q,billable_average=av,late_percent=lp,bad_amount_rows=bad,reopened_rows=reopen) for i,n,p,q,av,lp,bad,reopen in summary]}),settings={'groupKeyFields':'group_key'},acc=('ReportAcc',acc),change={'action':'hardened','reason':'Preserves claim month aggregation and adds null-only textual fallback, invalid override exclusion, waiver interplay and adjacent-status state.'},traps=['null-only override fallback','adjacent predecessor reset','amount validity independent from late population','half-up midpoint average']))
# T63: fiscal weighted exposure, exclusions and conditional group suppression.
fi=BASE+[DATE('valuation_at',False),Q('asset_value'),F('coverage_days','integer'),F('haircut_txt'),F('quote_currency'),F('risk_grade'),F('audit_required','boolean',False)]
fo=BASE+[F('fiscal_period',nullable=False),F('rows_seen','integer',False),F('eligible_rows','integer',False),F('excluded_rows','integer',False),F('weighted_days','integer',False),Q('adjusted_average',scale=3),Q('high_share',False)]
acc=BASE+[F('n','integer',False),F('eligible','integer',False),F('excluded','integer',False),F('days','integer',False),F('high_days','integer',False),Q('weighted_total',False,precision=24,scale=6)]
clauses=[
'Asset valuations reach a Rollup grouped by business_ref after sorting on that key. A group lies in one fiscal quarter, and its currency_cd is constant. Only output 0 is connected. The fiscal year begins April 1; January through March belong to quarter four of the preceding starting year. The source is prevalidated: each group has at most 1000 rows, each present coverage_days lies between -100000 and 100000 inclusive, and each non-null asset_value has absolute value at most 1000000. These bounds keep all group counts, day weights and weighted sums within their metadata precision.',
'For the summary copy every base context field from the first valuation, preserving null and empty notes and unused_archive_label. audit_required from that first valuation determines whether an empty eligible population is auditable; later audit_required values cannot change that decision.',
'An amount can be eligible only if quote_currency exactly matches the group currency, coverage_days is non-null and positive, and asset_value is non-null. Foreign currencies, null asset values, and missing or nonpositive coverage_days are excluded. For those excluded rows, never parse haircut_txt, even if it is garbage. Negative asset_value remains eligible and follows ordinary haircut rules.',
'For an otherwise eligible row, null or trimmed blank haircut_txt means zero percent haircut. A nonblank haircut must be ASCII digits, at most three integer digits and up to two fractional digits, and a decimal between zero and 100 inclusive. Invalid text, exponent, signs and out-of-range percentages exclude the row without throwing.',
'Each eligible row contributes coverage_days to weighted_days and asset_value times (100 minus haircut) divided by 100 times coverage_days to the weighted total. Keep exact decimal arithmetic throughout; negative asset values are legitimate corrections rather than exclusions.',
'adjusted_average is weighted total divided by weighted_days, rounded half-up to three decimal places. high_share is 100 times eligible coverage_days whose risk_grade is exactly HIGH divided by all weighted_days, rounded half-up to two places. Null, empty and differently cased grades contribute no HIGH weight.',
'rows_seen counts all arrivals, eligible_rows counts eligible arrivals, and excluded_rows counts every other arrival once. A zero eligible population yields adjusted_average null and high_share zero. Emit that empty-population summary only when the saved first audit_required is true; otherwise omit the whole group.',
'fiscal_period is the starting fiscal year followed by -Q and its quarter 1 through 4: April 2026 is 2026-Q1; UTC midnight January 1, 2026 is 2025-Q4. Use ordinary calendar year/month values, not ISO week-year. The reporting calendar is UTC, the host default timezone may differ, and valuation_at is non-null.',
'All sums, counts and first-row decisions are local to their group. Keep exact duplicate valuations as separate weights, preserve group order among surviving summaries, and correctly process a suppressed middle group and a final singleton. A bad haircut must not contaminate the next row or the next group.'
]
decl,save,emit=save_scalars(BASE,'first')
code=decl+'''boolean first_audit;
date first_date;
function void initGroup(ExposureAcc acc) {'''+save+'''first_audit=$in.0.audit_required;first_date=$in.0.valuation_at;acc.n=0;acc.eligible=0;acc.excluded=0;acc.days=0;acc.high_days=0;acc.weighted_total=0D;}
function boolean updateGroup(ExposureAcc acc) {
 acc.n++;boolean eligible=$in.0.quote_currency==$in.0.currency_cd && !isnull($in.0.coverage_days) && $in.0.coverage_days>0 && !isnull($in.0.asset_value);decimal haircut=0D;
 if(eligible) {string text=isnull($in.0.haircut_txt) ? "" : trim($in.0.haircut_txt);if(text!="") {if(!(text ~= "[0-9]{1,3}(\\\\.[0-9]{1,2})?")) eligible=false;else {haircut=str2decimal(text);if(haircut>100D) eligible=false;}}}
 if(!eligible) {acc.excluded++;return false;}
 acc.eligible++;acc.days+=$in.0.coverage_days;if($in.0.risk_grade=="HIGH") acc.high_days+=$in.0.coverage_days;
 acc.weighted_total+=$in.0.asset_value*(100D-haircut)/100D*$in.0.coverage_days;return false;
}
function integer updateTransform(integer counter,ExposureAcc acc) {return SKIP;}
function boolean finishGroup(ExposureAcc acc) {return acc.eligible>0 || first_audit;}
function integer transform(integer counter,ExposureAcc acc) {if(counter>0) return SKIP;'''+emit+'''integer m=getMonth(first_date,"UTC");integer y=getYear(first_date,"UTC");integer q;
 if(m<4) {y--;q=4;}else q=(m-4)/3+1;
 $out.0.fiscal_period=num2str(y)+"-Q"+num2str(q);$out.0.rows_seen=acc.n;$out.0.eligible_rows=acc.eligible;$out.0.excluded_rows=acc.excluded;$out.0.weighted_days=acc.days;
 $out.0.adjusted_average=acc.days==0 ? null : round(acc.weighted_total/acc.days,3);$out.0.high_share=acc.days==0 ? 0D : round(100D*acc.high_days/acc.days,2);return OK;
}'''
def val(k,n,**v):
 d=dict(valuation_at=D0,asset_value=None,coverage_days=None,haircut_txt=None,quote_currency='EUR',risk_grade=None,audit_required=False);d.update(v);return base(fi,k,n,**d)
s=[val('A',1,asset_value='10.00',coverage_days=1,risk_grade='HIGH',valuation_at='2026-03-31 23:30:00'),val('A',2,asset_value='20.00',coverage_days=2,haircut_txt='50',risk_grade='LOW'),val('A',3,asset_value='-3.00',coverage_days=1,haircut_txt='',risk_grade='high'),val('A',4,asset_value='99.00',coverage_days=3,haircut_txt='BAD:DATE',quote_currency='USD'),val('A',5,asset_value='99.00',coverage_days=1,haircut_txt='100.01'),val('B',6,asset_value=None,coverage_days=1,haircut_txt='bad',audit_required=False,valuation_at='2026-04-01 00:00:00'),val('B',7,asset_value='1.00',coverage_days=0,haircut_txt='bad',audit_required=True,valuation_at='2026-04-01 00:00:00'),val('C',8,asset_value=None,coverage_days=1,audit_required=True,valuation_at='2026-04-01 00:00:00'),val('D',9,asset_value='1.01',coverage_days=1,haircut_txt='50',risk_grade='HIGH',valuation_at='2026-12-31 00:00:00')]
# A weighted numerator=10*1 + 10*2 -3*1=27; denominator=4; HIGH weight=1.
items.append(make('T63',7,'Rollup','Fiscal asset exposure after weighted exclusions','Risk reporting asks for exposure after haircuts, weighted by covered days rather than the number of quotations. Foreign quotations and malformed haircut advice must remain in audit counts, while policy decides whether an entirely ineligible quarter merits a summary.',clauses,[('Valuation',fi)],[('Exposure',fo)],code,checks(clauses,['Uses one fiscal-quarter group in supplied order and the April fiscal boundary.','Saves all first-row context and only first audit_required.','Checks currency/day/value eligibility before parsing excluded-row haircuts.','Implements blank/null zero haircut and bounded valid decimal percent with safe failures.','Accumulates exact decimal weighted values and positive eligible day weights, allowing negative asset values.','Computes weighted half-up average scale 3 and exact HIGH day share scale 2.','Counts all/eligible/excluded once, defines zero population, and suppresses only unaudited empty groups.','Produces correct UTC fiscal starting year and quarter, including Jan/Apr midnight.','Resets every group, retains duplicate weights and handles suppressed/final groups.']),[('Must not average by row count, narrow decimal expressions to double, or treat lowercase high as HIGH.','Weights, exact arithmetic and code spelling are contractual.'),('Must not parse a foreign row\'s malformed haircut or emit every empty population unconditionally.','Eligibility precedes parsing and first-row audit controls suppression.')],fixture([s],{'0':[output(fo,s[0],fiscal_period='2025-Q4',rows_seen=5,eligible_rows=3,excluded_rows=2,weighted_days=4,adjusted_average='6.750',high_share='25.00'),output(fo,s[7],fiscal_period='2026-Q1',rows_seen=1,eligible_rows=0,excluded_rows=1,weighted_days=0,adjusted_average=None,high_share='0.00'),output(fo,s[8],fiscal_period='2026-Q3',rows_seen=1,eligible_rows=1,excluded_rows=0,weighted_days=1,adjusted_average='0.505',high_share='100.00')]}),settings={'groupKeyFields':'business_ref'},acc=('ExposureAcc',acc),traps=['weighted denominator','parse only eligible currencies','April fiscal starting year','first audit flag and empty group suppression']))
# Use actual component XML attribute names reported by the local guides.
for item in items:
 s=item['graph_spec']['settings']; c=item['test']['component'].split(' (')[0]
 if c=='Denormalizer' and 'groupKey' in s:s['key']=s.pop('groupKey')
 if c=='Rollup' and 'groupKey' in s:s['groupKeyFields']=s.pop('groupKey')
 if c=='ExtMergeJoin':s['joinKey']='$business_ref#$business_ref';s['joinType']='fullOuter'
for item in items:
 t=item['test'];g=item['graph_spec'];tid=t['test_id']
 if tid=='T55':
  for old,new in [
   ('Port 0 is the settlement follow-up writer and port 1 is the data-repair queue.','Only output 0 is connected to a reconciliation ledger. The ledger uses reconcile_kind REPAIR to send a row for data repair; other kinds identify settlement follow-ups.'),
   ('goes to repair with AMOUNT_TEXT','is retained as a REPAIR row with AMOUNT_TEXT'),
   ('goes to repair with EXPECTED_NULL','is retained as a REPAIR row with EXPECTED_NULL'),
   ('For repair output use','For a repair row use'),
   ('For follow-up output error_reason is empty.','For a follow-up row error_reason is empty.'),
   ('preserve the merger\'s output order within each destination.','preserve the merger\'s order in the reconciliation ledger.'),
   ('emit a repair and follow-up copy of one pair.','emit two different dispositions for one pair.')]:
   t['user_message']=t['user_message'].replace(old,new)
  # Remove the second metadata block and unsupported CTL output.
  t['user_message']=re.sub(r'Output metadata port 1:\n```xml\n.*?\n```\n\n','',t['user_message'],flags=re.S)
  t['reference']=t['reference'].replace('$out.1.','$out.0.').replace('return 1;','return OK;')
  t['reference']=t['reference'].replace('$out.0.*=$in.0.*;$out.0.*=$in.0.*;', '$out.0.*=$in.0.*;').replace('$out.0.*=$in.1.*;$out.0.*=$in.1.*;', '$out.0.*=$in.1.*;')
  g['outputMetadata']=g['outputMetadata'][:1]
  f=g['fixture'];both=f['expected']['0']+f['expected']['1'];both.sort(key=lambda z:z['business_ref']);f['expected']={'0':both}
  t['rubric']['required'][0]['check']='Uses field-level presence for both full-outer sides and emits one disposition on the sole transform output.'
  t['rubric']['required'][7]['check']='Sets REPAIR or follow-up annotations and complete context on output 0 in merge order.'
  item['change']['reason']='ExtMergeJoin full outer with absent sides, parse exemption and one-output business dispositions; runtime supports one transform output.'
 if tid=='T60':
  for old,new in [
   ('its output 0 feeds the version writer and output 1 feeds an audit queue.','its sole output 0 feeds an operation ledger that distinguishes version operations from audit records using record_kind.'),
   ('All these version records go to port 0; their record_kind supplies the operation.','All expansions go to output 0; record_kind supplies the version or audit operation.'),
   ('Audit rows are port 1 only; never broadcast a version row to the audit writer or obtain another key merely for the audit copy.','Audit rows carry their specified audit record_kind in the same ledger; never obtain another key merely for the audit copy.'),
   ('among requests within each output.','among requests in the ledger.'),
   ('ordered database operations and, where requested, a separate audit record.','ordered database operations and, where requested, an audit record in the same operation ledger.')]:t['user_message']=t['user_message'].replace(old,new)
  t['user_message']=re.sub(r'Output metadata port 1:\n```xml\n.*?\n```\n\n','',t['user_message'],flags=re.S)
  before,sep,after=t['reference'].partition('function integer transform(integer idx)')
  t['reference']=before+sep+after.replace('$out.1.','$out.0.').replace('return 1;','return OK;')
  g['outputMetadata']=g['outputMetadata'][:1]
  f=g['fixture'];both=f['expected']['0']+f['expected']['1'];both.sort(key=lambda z:z['source_row']);f['expected']={'0':both}
  t['rubric']['required'][0]['check']='Recognises CANCEL independently of previous presence and emits version/audit dispositions on the sole Normalizer output.'
  t['rubric']['required'][7]['check']='Copies all context and annotations to each expansion without reallocating audit keys.'
  item['change']['reason']='Normalizer close/open/audit expansion on one operation ledger, with parse precedence and sequence allocation per opening; runtime requires exactly one output.'
write_shard('shard_t54_t63.json',items)
