"""Round-two authoring T64–T73; expected business decisions are independent literal vectors."""
from rw2_common import make,field,decimal,write_shard
import json, hashlib

def dt(n,nullable=True,day=False):return field(n,'date',nullable,format='yyyy-MM-dd' if day else 'yyyy-MM-dd HH:mm:ss')
def ctx(prefix):
 return [field(prefix+'_key',nullable=False),field(prefix+'_tenant',nullable=False),field(prefix+'_file',nullable=False),field(prefix+'_row','long',False),dt(prefix+'_received',False),field(prefix+'_team'),field(prefix+'_market'),field(prefix+'_currency',nullable=False),field(prefix+'_batch',nullable=False),field(prefix+'_note'),field(prefix+'_trace'),field(prefix+'_unused_archive')]
def base(prefix,i):
 return {prefix+'_key':prefix.upper()+str(i),prefix+'_tenant':'ACME',prefix+'_file':prefix+'.csv',prefix+'_row':i,prefix+'_received':'2026-01-01 00:00:00',prefix+'_team':None if i%2 else 'OPS',prefix+'_market':'CZ',prefix+'_currency':'EUR',prefix+'_batch':'B1',prefix+'_note':'' if i==1 else None,prefix+'_trace':'X'+str(i),prefix+'_unused_archive':'keep:'+str(i)}
def checks(clauses,extra=None):
 out=[(c,'The numbered business contract determines this decision.',[i+1]) for i,c in enumerate(clauses)]
 return out+(extra or [])
def forb(*items):return [(s,'Violates the explicitly stated record or business decision.') for s in items]
def fix(inputs,expected,**kw):return dict(inputs=inputs,expected=expected,**kw)
def resources(**kw):return dict(parameters=kw.get('parameters',{}),lookups=kw.get('lookups',[]),sequences=kw.get('sequences',[]),dictionary=kw.get('dictionary',[]))
objects=[]

# T64: representative array hierarchy; one parent -> several children, optional properties.
p='basket'; fields=ctx(p)+[field('payload_json'),decimal('parent_value'),dt('business_dt',day=True)]
out=[f for f in fields if f['name']!='payload_json']+[field('child_code',nullable=False),field('child_note'),field('ordinal','integer',False),decimal('child_amount')]
clauses=[
'Flatten the basket JSON into child-table rows. A nonblank payload has an object root whose lines member is either missing, null or an array; null, empty and whitespace-only payloads, missing lines, null lines and an empty array each produce no children.',
'Array elements are objects with a required nonblank sku string. Preserve its exact spelling, internal and surrounding whitespace as child_code; repeated codes remain separate children. Parent references may repeat and must never be used as a cache key.',
'Assign ordinal from the original one-based array position, beginning with 1 and ending at the array length. Parents arrive in source order and all children of one parent precede the next parent’s children; no sorting or duplicate removal is permitted.',
'An optional details member is missing, null or an object. Its optional note is missing, null or a string. Missing/null details or note yields child_note null; an explicitly empty note stays empty, and every other note retains whitespace unchanged.',
'Child amount is missing, null or decimal text. Missing/null becomes child_amount null. A present blank or malformed decimal is a visible component failure, never zero, null, a skipped child or a skipped parent. Valid amounts consist of one through nine integer digits, optionally a dot and one or two fractional digits, optionally preceded by a minus; plus signs and surrounding whitespace are not accepted.',
'Copy every input field represented in child metadata unchanged, including nullable parent_value and business_dt. A date without time is midnight and survives as the same date. payload_json has no destination field and is not embedded in child notes.',
'Per-parent extraction state must be replaced before examining the next payload. A populated basket followed by a missing-array basket emits nothing for the latter, even if their basket_key values are identical.',
'Each valid array position emits exactly one output. Parent context belongs to its own source row, including the first and last inputs, empty notes and the archive field. If optional error hooks are supplied, log and propagate unexpected failures instead of acknowledging a partial basket as successful.'
]
code='''variant children;
function integer count() {
 children=null;
 if (isnull($in.0.payload_json) || trim($in.0.payload_json)=="") return 0;
 variant root=parseJson($in.0.payload_json);
 children=containsKey(root,"lines") ? root["lines"] : null;
 return isnull(children) ? 0 : length(children);
}
function integer transform(integer idx) {
 variant item=children[idx];
 $out.0.*=$in.0.*;
 $out.0.child_code=cast(item["sku"],string);$out.0.ordinal=idx+1;
 variant details=containsKey(item,"details") ? item["details"] : null;
 $out.0.child_note=null;
 if (!isnull(details) && containsKey(details,"note") && !isnull(details["note"])) $out.0.child_note=cast(details["note"],string);
 $out.0.child_amount=null;
 if (containsKey(item,"amount") && !isnull(item["amount"])) {
  string text=cast(item["amount"],string);
  if (!(text ~= "-?[0-9]{1,9}(\\\\.[0-9]{1,2})?")) raiseError("Invalid child amount shape");
  $out.0.child_amount=str2decimal(text);
 }
 return OK;
}
function void clean(){children=null;}
'''
payloads=[{'lines':[{'sku':' A ','details':{'note':''},'amount':'1.25'},{'sku':' A ','details':None,'amount':None},{'sku':'B','details':{'note':' x '},'amount':'-2.00'}]}, {},None,'', '   ', {'lines':None},{'lines':[]},{'lines':[{'sku':'LAST','details':{},'amount':'0.00'}]}]
rows=[]
for i,payload in enumerate(payloads,1):rows.append(dict(base(p,i),payload_json=json.dumps(payload) if isinstance(payload,dict) else payload,parent_value=None if i%2 else '12.50',business_dt=None if i==3 else '2026-01-01'))
rows[1]['basket_key']=rows[0]['basket_key']
expected=[]
for idx,codev,note,amount in [(1,' A ','','1.25'),(2,' A ',None,None),(3,'B',' x ','-2.00')]:expected.append(dict({k:v for k,v in rows[0].items() if k!='payload_json'},child_code=codev,child_note=note,ordinal=idx,child_amount=amount))
expected.append(dict({k:v for k,v in rows[7].items() if k!='payload_json'},child_code='LAST',child_note=None,ordinal=1,child_amount='0.00'))
objects.append(make('T64',8,'Normalizer (basket array extraction)','Basket rows retain optional nested notes',
'A checkout ingestion graph supplies validated JSON baskets to one Normalizer. The next writer stores children keyed by source-row identity and ordinal. Parent monetary and calendar fields have already been typed by the reader; unknown JSON properties are harmless. The component must retain the business context without interpreting optional absence as a reused value.',clauses,[('BasketEnvelope',fields)],[('BasketLine',out)],code,checks(clauses),forb('Must not cache children by basket_key or reuse a previous array.','Must not suppress invalid child amounts or change empty notes to null.'),fix([rows],{'0':expected},failure_probes=[{'name':'empty_amount','inputs':[[dict(rows[0],payload_json='{"lines":[{"sku":"X","amount":""}]}')]],'expected_failure':True},{'name':'malformed_amount','inputs':[[dict(rows[0],payload_json='{"lines":[{"sku":"X","amount":"bad"}]}')]],'expected_failure':True},{'name':'excess_integer_digits','inputs':[[dict(rows[0],payload_json='{"lines":[{"sku":"X","amount":"1000000000"}]}')]],'expected_failure':True},{'name':'excess_fraction_digits','inputs':[[dict(rows[0],payload_json='{"lines":[{"sku":"X","amount":"1.234"}]}')]],'expected_failure':True}]),change={'action':'kept','reason':'Preserved reviewed basket extraction; removed callback hints and made blank amounts fail explicitly.'},traps=['Optional variant-map keys','Null vs empty nested note','State reset after repeated parent key']))

# T65: variant map traversal; two dimensions differ: business and mechanism/edge cases.
p='machine';fields=ctx(p)+[field('channels_json'),decimal('rated_capacity'),dt('commissioned_on',day=True)]
out=[f for f in fields if f['name']!='channels_json']+[field('channel_name',nullable=False),field('position','integer',False),decimal('reading_value'),field('quality_cd',nullable=False)]
clauses=[
'The equipment payload is either null/blank or a JSON object with optional channels, itself missing, null or an object keyed by channel names. Empty envelopes and absent/null/empty channel maps produce zero observations. Each channel value is a non-null object and its key is a nonempty ASCII string.',
'Visit keys in ascending case-sensitive lexical order, independently of JSON property insertion order. position is the one-based position in this sorted list of all channel keys. A suppressed channel still occupies its position, so emitted positions may have gaps.',
'A channel has optional enabled, which is boolean or null. Only an explicit false suppresses the channel; missing and null enabled mean enabled. Suppressed entries may contain arbitrary malformed value text and must be discarded before reading or parsing that text.',
'For enabled entries the optional value is null, missing or a string. Missing/null/trimmed-empty becomes reading_value null and quality_cd MISSING. Distinguish genuine zero from missing and preserve a signed valid decimal exactly at two output places.',
'A nonblank value is valid only when its trimmed text matches an optional minus, one through six digits, and optionally a dot followed by one or two digits. Otherwise still emit the observation with null reading_value and quality_cd BAD_TEXT. Valid numeric text produces quality_cd GOOD; no conversion error may abort this graph.',
'The exact channel name is copied, without uppercasing. Metadata context including rated_capacity, commissioned_on, machine_note and machine_unused_archive accompanies each enabled entry; omit only channels_json from the child record.',
'Each equipment envelope starts with a new map and key list. Repeated machine_key values refer to separate measurements. A missing map after a populated map must produce no stale observations; a singleton map emits position 1 even on the final parent.',
'The output follows parent arrival order, then sorted channel-key order, retaining repeated equipment and repeated values. Resetting after all observations or before the next envelope are both valid; do not infer first-envelope detection from an uninitialized string/date being null.'
]
code='''variant channels;
string[] keys;
function integer count(){
 channels=null;clear(keys);
 if (isnull($in.0.channels_json) || trim($in.0.channels_json)=="") return 0;
 variant root=parseJson($in.0.channels_json);
 if (!containsKey(root,"channels") || isnull(root["channels"])) return 0;
 channels=root["channels"];
 foreach(variant key:getKeys(channels)) append(keys,cast(key,string));
 keys=sort(keys);return length(keys);
}
function integer transform(integer idx){
 variant entry=channels[keys[idx]];
 if (containsKey(entry,"enabled") && !isnull(entry["enabled"]) && !cast(entry["enabled"],boolean)) return SKIP;
 $out.0.*=$in.0.*;$out.0.channel_name=keys[idx];$out.0.position=idx+1;
 $out.0.reading_value=null;$out.0.quality_cd="MISSING";
 if (!containsKey(entry,"value") || isnull(entry["value"])) return OK;
 string raw=trim(cast(entry["value"],string));if(raw=="") return OK;
 if (!(raw ~= "-?[0-9]{1,6}(\\\\.[0-9]{1,2})?")) {$out.0.quality_cd="BAD_TEXT";return OK;}
 $out.0.reading_value=str2decimal(raw);$out.0.quality_cd="GOOD";return OK;
}
function void clean(){channels=null;clear(keys);}
'''
payloads=[{'channels':{'z':{'value':' -1.20 '},'B':{'enabled':False,'value':'BAD'},'A':{'value':'0'},'c':{'value':''}}},{}, {'channels':None},' ',{'channels':{'a':{'enabled':None,'value':'12.345'},'b':{},'c':{'value':'1000000'}}},None,{'channels':{}},{'channels':{'only':{'value':' 2.50 '}}}]
rows=[dict(base(p,i),channels_json=json.dumps(v) if isinstance(v,dict) else v,rated_capacity='10.00',commissioned_on='2020-06-01') for i,v in enumerate(payloads,1)];rows[1]['machine_key']=rows[0]['machine_key']
expected=[]
for ri,key,pos,value,quality in [(0,'A',1,'0.00','GOOD'),(0,'c',3,None,'MISSING'),(0,'z',4,'-1.20','GOOD'),(4,'a',1,None,'BAD_TEXT'),(4,'b',2,None,'MISSING'),(4,'c',3,None,'BAD_TEXT'),(7,'only',1,'2.50','GOOD')]:expected.append(dict({k:v for k,v in rows[ri].items() if k!='channels_json'},channel_name=key,position=pos,reading_value=value,quality_cd=quality))
objects.append(make('T65',8,'Normalizer (variant map observations)','Equipment channels are ordered by map key','A factory receives telemetry objects with dynamically named channels rather than a fixed sensor array. The Normalizer fans each envelope into an observation relation consumed by maintenance analytics. The schema validator guarantees object shapes and property types, but device firmware may still send bad numeric text. Disabled channels are intentionally opaque and should never trigger parsing failures.',clauses,[('EquipmentEnvelope',fields)],[('ChannelObservation',out)],code,checks(clauses),forb('Must not use JSON insertion order or renumber positions after suppression.','Must not parse a disabled entry or abort on an enabled malformed value.'),fix([rows],{'0':expected}),change={'action':'replaced','reason':'Replaces inspection-array clone with equipment map traversal, sorted dynamic keys and suppression before parsing.'},traps=['Sorted map keys','Suppression with ordinal gaps','Shape-capped decimal validation']))

# T66: representative payment Partition, interacting date and amount priority.
p='payment';fields=ctx(p)+[field('status_cd'),field('hold_flag','boolean',False),field('amount_txt'),field('invoice_day_txt'),field('priority_cd'),decimal('insured_value'),dt('due_at',day=True)]
clauses=[
'Six connected payment queues share the input metadata: 0 terminal, 1 manual hold, 2 overdue, 3 high value, 4 ordinary, and 5 defective text. Each row reaches exactly one queue. Apply the following rules in their numbered priority, preserving arrival order within each queue.',
'An exact REVERSED status wins queue 0, then hold_flag true wins queue 1. Neither branch examines amount_txt or invoice_day_txt. Status null, empty, different case and surrounding spaces do not qualify as terminal.',
'Only remaining rows inspect invoice_day_txt. Null, empty or whitespace-only means unknown invoice date. Otherwise trim, require exactly yyyy-MM-dd with two-digit month/day, and verify a real calendar date in UTC. Impossible dates and differently shaped dates go to defective queue 5, even when an amount or priority would otherwise qualify.',
'For a valid known invoice date, overdue means strictly before 2026-01-01. Such a row wins queue 2 without reading its amount, including malformed amount text. January 1 itself is not overdue; unknown invoice dates are not overdue.',
'After the preceding checks, trim amount_txt. Null/blank means zero. A nonblank value must have an optional leading minus, at most six integer digits, and optionally one or two fractional digits. Any other shape, excessive precision or invalid text goes to queue 5, including urgent rows.',
'A successfully interpreted amount at least 10000 wins queue 3. Negative values never qualify. Other rows use queue 4, except an exact URGENT priority combined with a strictly positive amount also wins queue 3. Empty/null priority and zero/negative urgent amounts remain ordinary.',
'Unexpected errors while evaluating a row must be logged and routed to queue 5. Invalid business text may be classified explicitly or by a logged error path; neither silent dropping nor component abortion is allowed. The downstream defect Reformat obtains its reason from its own validation and does not need this Partition to add fields.',
'Every edge carries the original record, including raw strings, nullable due_at and insured_value. No output construction, input edits or cross-row state is needed. Duplicate payment identifiers, the initial terminal row and the last urgent row must all survive exactly once.'
]
code='''function integer getOutputPort(){
 if($in.0.status_cd=="REVERSED")return 0;if($in.0.hold_flag)return 1;
 string dayText=trim(nvl($in.0.invoice_day_txt,""));
 if(dayText!=""){
  if(!(dayText ~= "[0-9]{4}-[0-9]{2}-[0-9]{2}") || !isDate(dayText,"yyyy-MM-dd","en.US","UTC",true))return 5;
  date invoice=str2date(dayText,"yyyy-MM-dd","en.US","UTC",true);
  if(invoice<createDate(2026,1,1,"UTC"))return 2;
 }
 string raw=trim(nvl($in.0.amount_txt,""));
 if(raw!="" && !(raw ~= "-?[0-9]{1,6}(\\\\.[0-9]{1,2})?"))return 5;
 decimal amount=raw=="" ? 0D : str2decimal(raw);
 if(amount>=10000D || ($in.0.priority_cd=="URGENT" && amount>0D))return 3;
 return 4;
}
function integer getOutputPortOnError(string message,string stackTrace){printLog(error,message);return 5;}
'''
values=[('REVERSED',False,'BAD','BAD',None,0),(None,True,'BAD','2025-02-30',None,1),('',False,'BAD','2025-12-31','URGENT',2),('',False,'10000','2025-02-30','URGENT',5),('',False,'10000','2026-1-1','URGENT',5),('',False,'10000','2026-01-01','URGENT',3),('',False,'0',None,'URGENT',4),('',False,'-1',' ','URGENT',4),(' reversed ',False,'1000000',None,None,5),('',False,'0.01',None,'URGENT',3),('',False,' ','2026-01-02',None,4),('',False,'bad',None,'URGENT',5)]
rows=[dict(base(p,i),status_cd=s,hold_flag=h,amount_txt=a,invoice_day_txt=d,priority_cd=q,insured_value=None,due_at='2026-01-01') for i,(s,h,a,d,q,port) in enumerate(values,1)];exp={str(i):[] for i in range(6)}
for row,v in zip(rows,values):exp[str(v[-1])].append(dict(row))
objects.append(make('T66',9,'Partition (payment priority with date defects)','Overdue payment routing bypasses irrelevant amount defects','A payment operations graph uses this Partition to feed terminal, held, overdue, review, routine and defect queues. A separate Reformat on the defect branch derives the reason; all Partition edges retain the full source record. Credit controllers care about old invoices before value-based review, so a defect in a lower-priority attribute must not displace a business decision already made.',clauses,[('PaymentRoute',fields)],[],code,checks(clauses),forb('Must not parse dates or amounts before a winning terminal or hold branch.','Must not let malformed date text reach a high-value or urgent queue.','Must not emit multiple destinations, SKIP records or normalize status codes.'),fix([rows],exp),change={'action':'hardened','reason':'Retains payment priority representative and adds date-shape/calendar guards plus overdue bypass and capped amount grammar.'},traps=['Priority bypasses malformed later fields','Calendar-validity versus date shape','URGENT requires positive value']))

# T67: new temperature Partition, prior-valid state and local timestamp defects.
p='cold';fields=ctx(p)+[field('trip_id',nullable=False),field('sample_no','integer',False),field('sensor_off','boolean',False),field('temperature_txt'),decimal('shipment_value'),dt('sample_time',False)]
clauses=[
'A refrigeration monitor routes each sample unchanged to one of five queues: 0 disabled sensors, 1 faulty measurement text, 2 missing samples, 3 alarm and 4 normal. Samples are sorted into contiguous trip_id groups and increasing sample_no; duplicate numbers are allowed and keep their arrival order. Upstream validation guarantees sample_no is an integer from 0 through 1000000000, so gaps are measured within that bounded counter domain.',
'The first record of each trip establishes fresh state: there is no previous valid temperature or sample number. Trip IDs are exact case-sensitive text. Use an explicit seen-valid flag because zero degrees and sample number zero are valid baseline values, not missing sentinels.',
'sensor_off true routes to queue 0 without inspecting temperature_txt. Disabled rows do not update the previous-valid baseline, even when their supplied temperature is well formed or the sample number is far ahead.',
'For active sensors, null, empty and trimmed-empty text routes to faulty queue 1. Otherwise accept exactly an optional minus, one or two integer digits, and optionally one fractional digit. Out-of-shape text also goes to 1; a valid parsed temperature must be between -50 and 50 inclusive or is faulty. Faulty rows leave the baseline unchanged.',
'Compare a valid sample to the preceding valid sample in the same trip. If a baseline exists and current sample_no exceeds its number by more than one, choose missing-sample queue 2, even if temperature would trigger an alarm. A duplicate sample number is not a gap.',
'If no gap wins, alarm queue 3 applies when temperature is above 8, below -20, or differs from the preceding valid temperature by more than 5 degrees in either direction. Threshold equality is safe. Without a predecessor only the absolute limits apply; remaining valid samples use queue 4.',
'Every valid active sample becomes the new baseline after its destination is decided, including a gap or alarm sample. Updating before comparison is incorrect. A following valid duplicate is compared with the immediately preceding valid sample, rather than an earlier record of the same numeric index.',
'Unexpected exceptions must be logged and reach faulty queue 1; they must not advance valid-state history. All source attributes including shipment_value, sample_time, notes and archive labels pass through. Keep all rows, including trip singletons and duplicate sample numbers, in per-queue arrival order.'
]
code='''string trip;boolean groupSeen=false;boolean validSeen=false;integer prevNo;decimal prevTemp;
function integer getOutputPort(){
 if(!groupSeen || trip!=$in.0.trip_id){trip=$in.0.trip_id;groupSeen=true;validSeen=false;}
 if($in.0.sensor_off)return 0;
 string raw=trim(nvl($in.0.temperature_txt,""));
 if(!(raw ~= "-?[0-9]{1,2}(\\\\.[0-9])?"))return 1;
 decimal t=str2decimal(raw);if(t < -50D || t > 50D)return 1;
 integer port=4;
 if(validSeen && $in.0.sample_no-prevNo>1)port=2;
 else if(t>8D || t < -20D || (validSeen && abs(t-prevTemp)>5D))port=3;
 prevNo=$in.0.sample_no;prevTemp=t;validSeen=true;return port;
}
function integer getOutputPortOnError(string message,string stackTrace){printLog(error,message);return 1;}
'''
values=[('A',0,False,'0',4),('A',1,True,'BAD',0),('A',2,False,'bad',1),('A',3,False,'12',2),('A',4,False,'7',4),('A',4,False,'1',3),('A',5,False,'-20',3),('B',0,False,'8',4),('B',1,False,'8.0',4),('B',2,False,'50.1',1),('B',2,False,'',1),('C',0,False,'-20',4)]
rows=[dict(base(p,i),trip_id=g,sample_no=n,sensor_off=off,temperature_txt=text,shipment_value='100.00',sample_time='2026-01-01 12:00:00') for i,(g,n,off,text,port) in enumerate(values,1)];exp={str(i):[] for i in range(5)}
for row,v in zip(rows,values):exp[str(v[-1])].append(dict(row))
objects.append(make('T67',9,'Partition (refrigeration history routing)','Cold-chain gaps outrank temperature alarms','A refrigerated carrier streams observations to a stateful Partition. The graph guarantees contiguous trips and numeric sample ordering, but disabled devices and malformed readings remain in the stream for operational accounting. The missing-sample queue is investigated separately from temperature alarms, and the same observation cannot be sent to both teams. Source metadata is carried unchanged to every downstream queue.',clauses,[('ColdSample',fields)],[],code,checks(clauses),forb('Must not update previous-valid state on disabled or faulty samples.','Must not compare after replacing the baseline or carry state into a new trip.','Must not use zero or a null check on an uninitialized scalar as the seen-valid condition.'),fix([rows],exp),change={'action':'replaced','reason':'Shipment monetary clone becomes cold-chain history routing; different domain, state mechanism and gap/error edge cases.'},traps=['Previous-valid sentinel','Malformed/disabled exclusion from state','Gap precedence and duplicate number']))

# T68: familiar library with compounded exact numeric contracts and null-zero precedence.
p='invoice';fields=ctx(p)+[field('raw_code'),decimal('gross_amount'),decimal('discount_percent'),decimal('surcharge_amount'),decimal('budget_amount'),dt('document_dt')]
out=fields+[field('clean_code'),decimal('net_amount'),decimal('budget_pct'),field('business_token')]
clauses=[
'Provide exactly four port-independent reusable functions named canonicalCode(string value), pricedAmount(decimal gross, decimal pct, decimal surcharge), budgetShare(decimal amount, decimal budget), and businessToken(string code, date value). They must use no mutable global state; the Reformat wrapper invokes them for every invoice.',
'canonicalCode returns null for null, otherwise trims surrounding whitespace and uppercases. Empty and whitespace-only remain empty strings. Internal spaces and delimiter characters are ordinary data, with no code validation or replacement sentinel.',
'pricedAmount returns null if gross or pct is null. A null surcharge means zero, independently of those required arguments. Otherwise its unrounded value is gross*(100-pct)/100+surcharge; round half-up exactly once at the final result to two places, never round the discount part before adding the surcharge.',
'Business input bounds are gross and surcharge from -1000000 to 1000000 and pct from -1000 to 1000, all at two fractional places. Negative gross, surcharge and percentages and pct above 100 remain allowed. Do not clamp, take absolute values or convert monetary calculation to floating point.',
'budgetShare returns null when amount or budget is null; null takes precedence over zero. A non-null zero budget returns exactly 0.00 even when amount is nonzero. Otherwise return amount/budget*100 half-up rounded to two places, retaining a negative sign where the ratio is negative.',
'businessToken returns null when either code or value is null; otherwise concatenate canonicalCode(code), a slash and the UTC calendar date yyyy-MM-dd. Empty code keeps the slash. Midnight dates are valid, and input date values must not be changed or formatted in the host timezone.',
'The wrapper copies all original invoice attributes. clean_code comes from raw_code; net_amount uses gross_amount, discount_percent and surcharge_amount; budget_pct uses the resulting net_amount and budget_amount, not gross; business_token uses raw_code and document_dt.',
'Every source row emits one record in arrival order, including duplicates and any combination of null arguments. First and final invoices follow identical function contracts. The notes, raw code, decimal inputs and unused archive label must remain exactly as read; no sequence, cache or external resource is available.'
]
code='''function string canonicalCode(string value){return isnull(value) ? null : upperCase(trim(value));}
function decimal pricedAmount(decimal gross,decimal pct,decimal surcharge){if(isnull(gross)||isnull(pct))return null;return round(gross*(100D-pct)/100D+nvl(surcharge,0D),2);}
function decimal budgetShare(decimal amount,decimal budget){if(isnull(amount)||isnull(budget))return null;if(budget==0D)return 0D;return round(amount/budget*100D,2);}
function string businessToken(string code,date value){if(isnull(code)||isnull(value))return null;return canonicalCode(code)+"/"+date2str(value,"yyyy-MM-dd","en.US","UTC");}
function integer transform(){$out.0.*=$in.0.*;$out.0.clean_code=canonicalCode($in.0.raw_code);$out.0.net_amount=pricedAmount($in.0.gross_amount,$in.0.discount_percent,$in.0.surcharge_amount);$out.0.budget_pct=budgetShare($out.0.net_amount,$in.0.budget_amount);$out.0.business_token=businessToken($in.0.raw_code,$in.0.document_dt);return OK;}
'''
# Literal tuples: source values then independently calculated clean/net/share/token.
values=[(' a b ','1.00','99.50','-0.01','1.00','2026-01-01 00:00:00','A B','-0.01','-1.00','A B/2026-01-01'),('', '10.00','0.00',None,'0.00','2026-01-01 23:00:00','','10.00','0.00','/2026-01-01'),(None,None,'0.00','1.00','0.00',None,None,None,None,None),(' x ', '10.00',None,None,'2.00',None,'X',None,None,None),(' neg ','-1.00','99.50',None,'1.00','2026-01-02 00:00:00','NEG','-0.01','-1.00','NEG/2026-01-02'),('above','10.00','150.00','1.00','-3.00','2026-01-03 00:00:00','ABOVE','-4.00','133.33','ABOVE/2026-01-03'),('  ', '5.00','-100.00','-2.00',None,'2026-01-04 00:00:00','','8.00',None,'/2026-01-04'),('a/b','12.50','20.00',None,'3.00','2026-01-05 00:00:00','A/B','10.00','333.33','A/B/2026-01-05')]
rows=[];expected=[]
for i,v in enumerate(values,1):
 codev,gross,pct,sur,bud,day,clean,net,share,token=v;row=dict(base(p,i),raw_code=codev,gross_amount=gross,discount_percent=pct,surcharge_amount=sur,budget_amount=bud,document_dt=day);rows.append(row);expected.append(dict(row,clean_code=clean,net_amount=net,budget_pct=share,business_token=token))
objects.append(make('T68',10,'Standalone / pure function (invoice pricing library)','Invoice utilities round once after the surcharge','An invoice loader applies a reusable CTL library through a Reformat wrapper. Monetary fields are already typed, and the application wants displayed identifiers, payable amounts and signed budget shares without losing original inputs. Output has to be independent of runtime timezone. The supplied ports are the wrapper metadata; no graph resources participate.',clauses,[('InvoiceUtilityInput',fields)],[('InvoiceUtilityOutput',out)],code,checks(clauses),forb('Must not round the discount subtotal before adding surcharge.','Must not let zero budget override a null amount or use integer division.','Must not coalesce a null public string argument to empty.'),fix([rows],{'0':expected}),change={'action':'hardened','reason':'Keeps invoice utility representative with chained net-budget output, final-only rounding and null-versus-zero precedence.'},traps=['Final-only HALF_UP rounding','Null before zero denominator','Output-to-function dependency']))

# T69: meter parsing library; helper contracts truly public, shape/error tokens.
p='meter';fields=ctx(p)+[field('current_text'),field('previous_text'),field('unit_code'),field('meter_status'),decimal('calibration_factor'),dt('captured_at')]
out=fields+[decimal('current_value'),decimal('delta_value'),field('delta_status',nullable=False),field('reading_label')]
clauses=[
'The shared library exports exactly four pure functions: readingValue(string text), readingDelta(string newer, string older), deltaStatus(string newer, string older), and readingLabel(string unit, string text). Port access belongs only to the surrounding Reformat. These functions carry no history between calls.',
'readingValue returns null for null, empty and whitespace-only input. Trim nonblank text and accept only an optional minus, one through five digits, and optionally a dot plus one or two fractional digits. Accepted zero and negative values become decimal values; a leading plus, comma, exponent, too many digits or excessive fractional precision instead yields null without throwing.',
'readingDelta parses each argument under that same contract. Return null if either argument lacks a valid numeric value, otherwise newer minus older, retaining negative consumption deltas. Do not turn a missing old reading into zero and do not round individual parsed values.',
'deltaStatus gives NEW_BAD when newer is nonblank but invalid. This outranks any older defect. Otherwise a nonblank invalid older gives OLD_BAD, even if newer is missing. Missing here means null or trimmed-empty, while malformed nonblank is a separate condition.',
'If neither malformed-text rule applies, deltaStatus gives MISSING when either side is missing; otherwise RESET for a negative delta, SAME for zero delta and ADVANCE for a positive delta. Numerical zero must remain present rather than being used as a missing sentinel.',
'readingLabel returns null if unit is null or text has no valid reading. Otherwise uppercase the trimmed unit, append a colon and render readingValue(text) in en.US with exactly two fractional digits and no grouping. An empty/whitespace unit stays empty before the colon; internal unit whitespace is retained.',
'The wrapper copies every source attribute and assigns current_value from current_text, delta_value and delta_status from current_text/previous_text, and reading_label from unit_code/current_text. meter_status, calibration_factor and captured_at are informational and must not affect interpretation.',
'Emit each source row, including first/last and duplicates, in arrival order even for malformed text. All four public functions must give the same result when invoked independently by a different graph. Preserve raw numeric strings, dates, null notes and the unused archive field unchanged.'
]
code='''function decimal readingValue(string text){string raw=trim(nvl(text,""));if(!(raw ~= "-?[0-9]{1,5}(\\\\.[0-9]{1,2})?"))return null;return str2decimal(raw);}
function decimal readingDelta(string newer,string older){decimal n=readingValue(newer);decimal o=readingValue(older);return isnull(n)||isnull(o) ? null : n-o;}
function string deltaStatus(string newer,string older){decimal n=readingValue(newer);decimal o=readingValue(older);if(!isBlank(newer)&&isnull(n))return "NEW_BAD";if(!isBlank(older)&&isnull(o))return "OLD_BAD";if(isnull(n)||isnull(o))return "MISSING";if(n<o)return "RESET";return n==o ? "SAME" : "ADVANCE";}
function string readingLabel(string unit,string text){decimal value=readingValue(text);return isnull(unit)||isnull(value) ? null : upperCase(trim(unit))+":"+num2str(value,"0.00","en.US");}
function integer transform(){$out.0.*=$in.0.*;$out.0.current_value=readingValue($in.0.current_text);$out.0.delta_value=readingDelta($in.0.current_text,$in.0.previous_text);$out.0.delta_status=deltaStatus($in.0.current_text,$in.0.previous_text);$out.0.reading_label=readingLabel($in.0.unit_code,$in.0.current_text);return OK;}
'''
values=[('0','0',' kWh ','0.00','0.00','SAME','KWH:0.00'),(' 12.50 ','10','kWh','12.50','2.50','ADVANCE','KWH:12.50'),('-1','2',' ','-1.00','-3.00','RESET',':-1.00'),('bad','bad','kWh',None,None,'NEW_BAD',None),(None,'oops','kWh',None,None,'OLD_BAD',None),('1',None,None,'1.00',None,'MISSING',None),(' ','0','kWh',None,None,'MISSING',None),('+1','0','kWh',None,None,'NEW_BAD',None),('100000','0','kWh',None,None,'NEW_BAD',None),('1.234','0','kWh',None,None,'NEW_BAD',None),('2','2','','2.00','0.00','SAME',':2.00'),('3.01','2.99','m 3','3.01','0.02','ADVANCE','M 3:3.01')]
rows=[];expected=[]
for i,v in enumerate(values,1):
 new,old,unit,cur,delta,status,label=v;row=dict(base(p,i),current_text=new,previous_text=old,unit_code=unit,meter_status='ACTIVE',calibration_factor='1.00',captured_at='2026-01-01 00:00:00');rows.append(row);expected.append(dict(row,current_value=cur,delta_value=delta,delta_status=status,reading_label=label))
objects.append(make('T69',10,'Standalone / pure function (meter parsing library)','Meter utility distinguishes malformed text from absent readings','A utilities gateway uses the same four CTL functions from several ingestion graphs. This task supplies their Reformat consumer with raw meter strings; malformed firmware readings remain audit rows instead of throwing away the source record. The library classifies missing, malformed and reset readings independently of operational meter status. Decimal formatting for labels must remain stable across locale settings.',clauses,[('MeterUtilityInput',fields)],[('MeterUtilityOutput',out)],code,checks(clauses),forb('Must not default missing readings to zero or parse out-of-shape text.','Must not prioritize OLD_BAD before NEW_BAD or MISSING before malformed text.','Must not share mutable history across public function calls.'),fix([rows],{'0':expected}),change={'action':'replaced','reason':'Consignment pricing clone becomes bounded meter-text parsing with precedence-based error statuses and negative deltas.'},traps=['Malformed vs missing public contracts','Two-argument error precedence','Regex caps and signed delta']))

# T70: representative fixture triples, stateful per-customer subtotal and discounts.
p='fixture';fields=ctx(p)+[field('fixture_id','long',False),field('customer_id','long',False),field('line_no','integer',False),decimal('unit_price',False),field('quantity','integer',False),decimal('line_total',False),decimal('customer_total',False),decimal('discount_pct',False),dt('event_dt',False,True),field('fixture_state',nullable=False)]
clauses=[
'The DataGenerator has no input and one connected output. Graph parameter FIXTURE_ROWS defaults to 8 and the component already has recordsNumber=${FIXTURE_ROWS}; allowed counts are 0 through 20. Generate exactly that configured population, with no CTL-driven abort or skipped generated row.',
'Use one-based source row n beginning at 1. fixture_id is 100000+n, customer_id is 1000 plus the integer quotient (n-1)/3, and line_no is (n-1)%3+1. Incomplete final triples remain valid. fixture_row is n as a long, and each generated identifier must agree with the same row number.',
'unit_price is 12.50 plus line_no and quantity equals line_no. The first customer uses discount_pct 0, the next 10, then 0, alternating by zero-based customer index rather than by individual line. Discounts apply to every line of the same customer.',
'line_total is unit_price*quantity*(100-discount_pct)/100, using decimal arithmetic and half-up rounding to two places. Never derive the total by parsing text or by integer percentage division. Negative or random fixture prices are not part of this scenario.',
'customer_total is the running sum of already rounded line totals within this customer, including the current line. Reset it before every line_no 1, even when the previous customer was incomplete in an earlier run. The first subtotal is 13.50, rather than null or an old accumulator value.',
'event_dt is UTC midnight 2026-01-01 plus n-1 calendar days; fixture_received is the same instant. fixture_state is OPEN for odd n and CLOSED for even n, independent of customer discount. A one-row run begins on January 1 with OPEN.',
'Set fixture_key to FIX- followed by fixture_id in ordinary base-10, fixture_trace to CUST- followed by customer_id, fixture_tenant TEST, fixture_file synthetic, fixture_currency EUR and fixture_batch FIXTURE. Explicitly assign fixture_team, fixture_market, fixture_note and fixture_unused_archive null on every row.',
'A fresh component starts its row counter and subtotal state from zero. Do not reset the row counter at customer boundaries. Every successful generation returns an emitting result, including the last call; the component’s configured count also handles zero without manufacturing an initial row. Explain that ownership of row count in a code comment.'
]
code='''integer n=0;decimal subtotal=0D;
// recordsNumber owns the finite row count, including zero.
function integer generate(){
 n++;integer customerIndex=(n-1)/3;
 $out.0.fixture_id=100000L+n;$out.0.customer_id=1000L+customerIndex;
 $out.0.line_no=(n-1)%3+1;$out.0.unit_price=12.50D+$out.0.line_no;$out.0.quantity=$out.0.line_no;
 $out.0.discount_pct=customerIndex%2==0 ? 0D : 10D;
 $out.0.line_total=round($out.0.unit_price*$out.0.quantity*(100D-$out.0.discount_pct)/100D,2);
 if($out.0.line_no==1)subtotal=0D;subtotal=subtotal+$out.0.line_total;$out.0.customer_total=subtotal;
 $out.0.event_dt=dateAdd(createDate(2026,1,1,"UTC"),n-1,day);$out.0.fixture_received=$out.0.event_dt;
 $out.0.fixture_state=n%2==1 ? "OPEN" : "CLOSED";
 $out.0.fixture_key="FIX-"+num2str($out.0.fixture_id);$out.0.fixture_trace="CUST-"+num2str($out.0.customer_id);
 $out.0.fixture_tenant="TEST";$out.0.fixture_file="synthetic";$out.0.fixture_row=n;$out.0.fixture_currency="EUR";$out.0.fixture_batch="FIXTURE";
 $out.0.fixture_team=null;$out.0.fixture_market=null;$out.0.fixture_note=null;$out.0.fixture_unused_archive=null;return OK;
}
'''
values=[(1000,1,'13.50','0.00','13.50','13.50'),(1000,2,'14.50','0.00','29.00','42.50'),(1000,3,'15.50','0.00','46.50','89.00'),(1001,1,'13.50','10.00','12.15','12.15'),(1001,2,'14.50','10.00','26.10','38.25'),(1001,3,'15.50','10.00','41.85','80.10'),(1002,1,'13.50','0.00','13.50','13.50'),(1002,2,'14.50','0.00','29.00','42.50')]
expected=[]
for n,v in enumerate(values,1):
 customer,line,price,disc,total,cum=v;expected.append(dict(base(p,n),fixture_key='FIX-'+str(100000+n),fixture_tenant='TEST',fixture_file='synthetic',fixture_received=f'2026-01-{n:02} 00:00:00',fixture_team=None,fixture_market=None,fixture_currency='EUR',fixture_batch='FIXTURE',fixture_note=None,fixture_trace='CUST-'+str(customer),fixture_unused_archive=None,fixture_id=100000+n,customer_id=customer,line_no=line,unit_price=price,quantity=line,line_total=total,customer_total=cum,discount_pct=disc,event_dt=f'2026-01-{n:02}',fixture_state='OPEN' if n%2 else 'CLOSED'))
objects.append(make('T70',11,'DataGenerator (order fixture subtotals)','Order fixtures alternate discounts per customer','An order assertion graph runs this DataGenerator in UTC and writes generated line items to a reconciliation collector. It sets a finite component row count from FIXTURE_ROWS before execution. The fixture retains three-line customer relationships while adding realistic discounted totals and a subtotal that must carry across calls within one customer and reset before the next. No external sequences, random source or live clock are available.',clauses,[],[('OrderFixture',fields)],code,checks(clauses),forb('Must not return STOP or SKIP to implement the configured row count.','Must not alternate discount every row or carry customer_total into the next customer.','Must not identify first use through null-testing an uninitialized integer/decimal.'),fix([],{'0':expected},rows_count=8,parameters={'FIXTURE_ROWS':'8'},boundary_probes=[dict(name='zero_rows',parameters={'FIXTURE_ROWS':'0'},resources={'parameters':{'FIXTURE_ROWS':'0'}},rows_count=0,inputs=[],expected={'0':[]}),dict(name='one_row',parameters={'FIXTURE_ROWS':'1'},resources={'parameters':{'FIXTURE_ROWS':'1'}},rows_count=1,inputs=[],expected={'0':expected[:1]}),dict(name='partial_customer',parameters={'FIXTURE_ROWS':'4'},resources={'parameters':{'FIXTURE_ROWS':'4'}},rows_count=4,inputs=[],expected={'0':expected[:4]})]),settings={'recordsNumber':'${FIXTURE_ROWS}'},resources=resources(parameters={'FIXTURE_ROWS':'8'}),change={'action':'hardened','reason':'Preserves order triples; adds alternating customer discount and rounded running subtotal with boundary reset.'},traps=['Per-customer rather than per-row parity','Subtotal reset before first line','Finite zero-count ownership']))

# T71: recurrence fixture unrelated to order triples; first-step sentinel and clipped carry.
p='tank';fields=ctx(p)+[field('step_no','integer',False),decimal('prior_level',False),decimal('inflow',False),decimal('withdrawal',False),decimal('stored_level',False),decimal('spill_amount',False),decimal('total_spill',False),dt('simulation_day',False,True),field('level_band',nullable=False)]
clauses=[
'A reservoir regression graph provides this DataGenerator no input and one output. STEPS defaults to 9 and already controls the component recordsNumber; it is an integer from 0 to 20. Each requested step emits one row; zero requested steps emits none. Successful final generation must not abort the graph.',
'The simulation starts with 5.00 units stored before step 1. step_no and tank_row are one-based. prior_level is the previous step’s stored_level, with exactly 5.00 for the first row. A stored zero is real state; never reinitialize merely because the previous level is zero.',
'Inflow repeats a three-step cycle 7.00, 0.00, 4.00 except scheduled flushing at step 4 supplies 10.00. Withdrawal is 3.00 on odd steps and 8.00 on even steps, except step 4 has zero withdrawal. Both exceptions use global step number, and cycles do not restart when storage becomes empty or full.',
'For each step compute the unclipped value as prior_level+inflow-withdrawal. Capacity is 10.00; stored_level is the unclipped value clipped into [0,10]. spill_amount is max(the unclipped value-10,0). A negative raw level produces stored zero and spill zero, not a negative amount.',
'Carry only stored_level into the following step, not the unclipped result. total_spill accumulates spill_amount across the entire run, beginning with the current first spill. All calculations are decimal and all six numeric measurement fields are explicitly assigned every row.',
'level_band is EMPTY when stored_level equals zero, FULL when it equals ten, otherwise PARTIAL. Threshold equality must select the boundary bands. The first step is PARTIAL with level 9.00, and the fourth step overflows by 2.00.',
'simulation_day starts at UTC midnight 2026-02-01 and advances by one calendar day per step; tank_received is the same instant. tank_key is SIM- plus step_no, tank_trace is STEP- plus step_no. Set tenant LAB, file reservoir, currency UNIT and batch SIM; explicitly null team, market, note and archive.',
'A new run restores initial storage 5.00 and accumulated spill zero. Preserve step order even when levels repeat, including first and last rows. No input record, lookup, sequence, dictionary or current-time dependency is available, and a code comment must state that configured recordsNumber owns termination.'
]
code='''integer step=0;decimal level=5D;decimal spillTotal=0D;
// recordsNumber owns termination and does not call generate for zero steps.
function integer generate(){
 step++;$out.0.step_no=step;$out.0.prior_level=level;
 integer cycle=(step-1)%3;$out.0.inflow=cycle==0 ? 7D : cycle==1 ? 0D : 4D;
 if(step==4)$out.0.inflow=10D;
 $out.0.withdrawal=step==4 ? 0D : step%2==1 ? 3D : 8D;
 decimal raw=level+$out.0.inflow-$out.0.withdrawal;
 level=raw<0D ? 0D : raw>10D ? 10D : raw;
 $out.0.stored_level=level;$out.0.spill_amount=raw>10D ? raw-10D : 0D;
 spillTotal=spillTotal+$out.0.spill_amount;$out.0.total_spill=spillTotal;
 $out.0.level_band=level==0D ? "EMPTY" : level==10D ? "FULL" : "PARTIAL";
 $out.0.simulation_day=dateAdd(createDate(2026,2,1,"UTC"),step-1,day);$out.0.tank_received=$out.0.simulation_day;
 $out.0.tank_key="SIM-"+num2str(step);$out.0.tank_trace="STEP-"+num2str(step);$out.0.tank_row=step;
 $out.0.tank_tenant="LAB";$out.0.tank_file="reservoir";$out.0.tank_currency="UNIT";$out.0.tank_batch="SIM";
 $out.0.tank_team=null;$out.0.tank_market=null;$out.0.tank_note=null;$out.0.tank_unused_archive=null;return OK;
}
'''
# Hand recurrence: prior/inflow/withdrawal/stored/spill/cumulative/band.
values=[('5.00','7.00','3.00','9.00','0.00','0.00','PARTIAL'),('9.00','0.00','8.00','1.00','0.00','0.00','PARTIAL'),('1.00','4.00','3.00','2.00','0.00','0.00','PARTIAL'),('2.00','10.00','0.00','10.00','2.00','2.00','FULL'),('10.00','0.00','3.00','7.00','0.00','2.00','PARTIAL'),('7.00','4.00','8.00','3.00','0.00','2.00','PARTIAL'),('3.00','7.00','3.00','7.00','0.00','2.00','PARTIAL'),('7.00','0.00','8.00','0.00','0.00','2.00','EMPTY'),('0.00','4.00','3.00','1.00','0.00','2.00','PARTIAL')]
expected=[]
for n,v in enumerate(values,1):
 prior,flow,withdraw,stored,spill,total,band=v;expected.append(dict(base(p,n),tank_key='SIM-'+str(n),tank_tenant='LAB',tank_file='reservoir',tank_received=f'2026-02-{n:02} 00:00:00',tank_team=None,tank_market=None,tank_currency='UNIT',tank_batch='SIM',tank_note=None,tank_trace='STEP-'+str(n),tank_unused_archive=None,step_no=n,prior_level=prior,inflow=flow,withdrawal=withdraw,stored_level=stored,spill_amount=spill,total_spill=total,simulation_day=f'2026-02-{n:02}',level_band=band))
objects.append(make('T71',11,'DataGenerator (reservoir state recurrence)','Reservoir recurrence carries clipped storage','A water-engineering test graph creates deterministic simulation steps for a reservoir controller. The graph supplies STEPS as its finite DataGenerator record count and runs in UTC. The receiving assertion collector checks that capacity clipping changes the next step’s starting state and that accumulated spill persists through later empty storage. This is a synthetic mathematical fixture with no reader or external resource state.',clauses,[],[('ReservoirFixture',fields)],code,checks(clauses),forb('Must not reinitialize prior storage when stored_level is zero.','Must not carry raw unclipped storage or reset cumulative spill at empty/full boundaries.','Must not return STOP, introduce random values or skip the last configured step.'),fix([],{'0':expected},rows_count=9,parameters={'STEPS':'9'},boundary_probes=[dict(name='zero_steps',parameters={'STEPS':'0'},resources={'parameters':{'STEPS':'0'}},rows_count=0,inputs=[],expected={'0':[]}),dict(name='one_step',parameters={'STEPS':'1'},resources={'parameters':{'STEPS':'1'}},rows_count=1,inputs=[],expected={'0':expected[:1]})]),settings={'recordsNumber':'${STEPS}'},resources=resources(parameters={'STEPS':'9'}),change={'action':'replaced','reason':'Maintenance order clone replaced with clipped reservoir recurrence, overflow accumulation and scheduled exceptional step.'},traps=['Zero is a valid carried state','Clipping before recurrence','Global cycle and exceptional-step precedence']))

# T72: representative framed receipt digest and real resources.
p='receipt';fields=ctx(p)+[field('merchant_cd'),field('transaction_ref'),decimal('posted_amount'),dt('posting_dt')]
out=fields+[field('run_id',nullable=False),dt('run_ts',False),field('audit_seq','long',False),field('record_digest',nullable=False),field('audit_source',nullable=False)]
clauses=[
'The orchestration supplies AUDIT_RUN_ID, RUN_TS and SOURCE_FILE graph parameters; example values are R2-A, 2026-01-05 08:00:00 and receipts.csv. Read current parameter values into run_id and audit_source. Parse RUN_TS as a strict UTC yyyy-MM-dd HH:mm:ss timestamp into run_ts; do not overwrite receipt_file.',
'The digest tuple is merchant_cd, transaction_ref, posted_amount and posting_dt, in that order. A null component is represented by N. Each non-null string is V followed by exact original text, including empty strings, surrounding whitespace, colons and pipes; trimming or case folding would change identity.',
'A non-null amount is V followed by en.US fixed two-decimal text without grouping, rounded half-up if needed. Input amounts are within +/-1000000. A non-null posting date is V followed by its UTC yyyy-MM-dd HH:mm:ss representation, with explicit midnight time when appropriate.',
'Frame each represented part as its decimal CTL string length, a colon and the entire represented part. Length includes the marker and counts UTF-16 code units. Concatenate all four frames with no additional separator. A delimiter inside a string is data, never a boundary.',
'record_digest is lowercase hexadecimal SHA-256 of that complete framed string. Equivalent supported hash/hex conversions are valid. Null merchant and empty merchant must differ. Duplicate selected tuples must produce the same digest even when their receipt context or audit sequence differs.',
'A graph-managed sequence AuditRows begins at 1 with step 1 and must be accessed as long. Each source row consumes exactly one next value into audit_seq during record transformation, including duplicate tuples. Do not reset the sequence or read it during initialization/shutdown.',
'Copy all original fields unchanged, including original filename, timestamps, exact text inputs, nullable receipt_note and receipt_unused_archive. The new audit_source names the orchestration source; it does not alter any original source attribute.',
'Emit one output per input in source order and retain the first, final and duplicate rows. No digest cache may suppress rows or suppress sequence consumption. Any unexpected hashing error must fail visibly rather than silently acknowledge a missing audit record.'
]
code='''function string frame(string v){return num2str(length(v))+":"+v;}
function string mark(string v){return isnull(v)?"N":"V"+v;}
function integer transform(){
 $out.0.*=$in.0.*;$out.0.run_id=getParamValue("AUDIT_RUN_ID");$out.0.audit_source=getParamValue("SOURCE_FILE");
 $out.0.run_ts=str2date(getParamValue("RUN_TS"),"yyyy-MM-dd HH:mm:ss","en.US","UTC",true);
 string a=mark($in.0.merchant_cd);string b=mark($in.0.transaction_ref);
 string c=isnull($in.0.posted_amount)?"N":"V"+num2str(round($in.0.posted_amount,2),"0.00","en.US");
 string d=isnull($in.0.posting_dt)?"N":"V"+date2str($in.0.posting_dt,"yyyy-MM-dd HH:mm:ss","en.US","UTC");
 $out.0.record_digest=lowerCase(sha256HexString(frame(a)+frame(b)+frame(c)+frame(d)));
 $out.0.audit_seq=sequence(AuditRows,long).next();return OK;
}
'''
values=[(None,'A','1.00','2026-01-01 00:00:00'),('','A','1.00','2026-01-01 00:00:00'),(' x ','a|:','-1.25','2026-01-01 12:34:56'),('x','a|:',None,None),('x','a|:','0.00',None),('x','a|:','0.00','2026-01-01 00:00:00'),(' x ','a|:','-1.25','2026-01-01 12:34:56'),('LAST','','10.00','2026-01-02 00:00:00')]
# These are independently represented business tuples, not execution of reference code.
representations=[['N','VA','V1.00','V2026-01-01 00:00:00'],['V','VA','V1.00','V2026-01-01 00:00:00'],['V x ','Va|:','V-1.25','V2026-01-01 12:34:56'],['Vx','Va|:','N','N'],['Vx','Va|:','V0.00','N'],['Vx','Va|:','V0.00','V2026-01-01 00:00:00'],['V x ','Va|:','V-1.25','V2026-01-01 12:34:56'],['VLAST','V','V10.00','V2026-01-02 00:00:00']]
rows=[];expected=[]
for i,(v,parts) in enumerate(zip(values,representations),1):
 merchant,transaction,amount,day=v;row=dict(base(p,i),merchant_cd=merchant,transaction_ref=transaction,posted_amount=amount,posting_dt=day);rows.append(row)
 canonical=''.join(str(len(z.encode('utf-16-le'))//2)+':'+z for z in parts)
 expected.append(dict(row,run_id='R2-A',run_ts='2026-01-05 08:00:00',audit_seq=i,record_digest=hashlib.sha256(canonical.encode('utf-8')).hexdigest(),audit_source='receipts.csv'))
objects.append(make('T72',12,'Reformat (receipt audit digest)','Receipt audit identities use framed business tuples','An append-only receipt audit graph puts this Reformat before its ledger writer. Orchestration parameters carry the run identity and file name, while AuditRows provides long row identifiers independently of the business digest. The audit comparison tool treats null, empty text and delimiter-bearing references as distinct selected tuples. Records with a repeated business identity still represent separate source arrivals.',clauses,[('ReceiptSource',fields)],[('ReceiptAudited',out)],code,checks(clauses),forb('Must not delimiter-join raw tuple values or collapse null into empty.','Must not consume sequence during setup, reset it, or skip a repeated digest.','Must not use the current clock or substitute audit_source for receipt_file.'),fix([rows],{'0':expected}),resources=resources(parameters={'AUDIT_RUN_ID':'R2-A','RUN_TS':'2026-01-05 08:00:00','SOURCE_FILE':'receipts.csv'},sequences=[{'name':'AuditRows','start':1,'step':1}]),change={'action':'kept','reason':'Preserves collision-safe receipt audit representative with full runtime fixture and parameter/sequence resources.'},traps=['Null/empty injective framing','Long sequence independent of digest','Raw source versus orchestration source']))

# T73: dictionary state audit; disabled bypass and first/previous accepted sentinel.
p='claim';fields=ctx(p)+[field('audit_requested','boolean',False),field('submitted_txt'),decimal('claimed_amount'),field('claim_class')]
out=fields+[field('audit_state',nullable=False),field('audit_label'),dt('accepted_at'),field('accepted_index','long',False),decimal('accepted_running',False),field('previous_claim_key')]
clauses=[
'The graph dictionary supplies auditEnabled boolean true, auditLabel string CLAIMS-R2, and cutoffText string 2026-01-01 00:00:00. These entries may change between runs. Dictionary auditEnabled is the run-level switch, while audit_requested is each row’s request; neither substitutes for the other.',
'If auditing is disabled for the run or not requested by this row, emit audit_state BYPASS, audit_label null, accepted_at null, accepted_index zero, accepted_running equal to the current accepted monetary total, and previous_claim_key null. Do not inspect submitted_txt or parse cutoffText on this branch.',
'For a requested enabled row, submitted_txt must be present and match exactly yyyy-MM-dd HH:mm:ss before strict UTC calendar parsing. Null, blank, impossible dates and different shapes yield audit_state BAD_TIME, null accepted_at and previous_claim_key, index zero and the unchanged running total. These are ordinary output records, not thrown errors.',
'Parse dictionary cutoffText strictly in UTC only when a row reaches valid submission-time evaluation. It is guaranteed valid when auditing is enabled. A submitted timestamp before the cutoff yields audit_state TOO_OLD with the same nonaccepted outputs as BAD_TIME; equality is accepted.',
'An accepted row emits audit_state ACCEPTED and its parsed submitted time into accepted_at. accepted_index counts only accepted records, one-based across the whole stream. Rejected/bypassed rows do not consume an index or advance accepted-history state.',
'claimed_amount may be null, zero or negative within +/-1000000; null contributes zero to the accepted running total. Add the current accepted amount before emitting accepted_running. For every nonaccepted row preserve the total already accumulated, including when it is zero.',
'previous_claim_key is null on the first accepted record; otherwise it is the exact claim_key from the immediately preceding accepted record, skipping all intervening nonaccepted rows. Empty claim_key is allowed and must be remembered as a valid prior key. Use explicit accepted-history state, not null testing a default string/date.',
'audit_label equals the current dictionary label on enabled/requested rows, including BAD_TIME and TOO_OLD, but remains null on bypasses. Copy every original claim field unchanged; emit every source row in arrival order, retain duplicates and do not reorder claims by parsed timestamp.',
'A new component execution starts accepted index and monetary total at zero with no preceding accepted key. Dictionary entries are read-only configuration and must never be mutated to store counters. Unexpected errors after business guards must fail visibly or log before propagating; no silent skipping is permitted.'
]
# claim key deliberately nullable=false still allows explicit empty due nullValue custom token.
code='''long acceptedCount=0L;decimal total=0D;boolean seenAccepted=false;string previous;
function integer transform(){
 $out.0.*=$in.0.*;$out.0.accepted_at=null;$out.0.accepted_index=0L;$out.0.previous_claim_key=null;
 $out.0.accepted_running=total;$out.0.audit_label=null;
 if(!dictionary.auditEnabled || !$in.0.audit_requested){$out.0.audit_state="BYPASS";return OK;}
 $out.0.audit_label=dictionary.auditLabel;
 string raw=nvl($in.0.submitted_txt,"");
 if(!(raw ~= "[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}") || !isDate(raw,"yyyy-MM-dd HH:mm:ss","en.US","UTC",true)){$out.0.audit_state="BAD_TIME";return OK;}
 date submitted=str2date(raw,"yyyy-MM-dd HH:mm:ss","en.US","UTC",true);
 date cutoff=str2date(dictionary.cutoffText,"yyyy-MM-dd HH:mm:ss","en.US","UTC",true);
 if(submitted<cutoff){$out.0.audit_state="TOO_OLD";return OK;}
 acceptedCount++;total=total+nvl($in.0.claimed_amount,0D);
 $out.0.audit_state="ACCEPTED";$out.0.accepted_at=submitted;$out.0.accepted_index=acceptedCount;$out.0.accepted_running=total;
 if(seenAccepted)$out.0.previous_claim_key=previous;previous=$in.0.claim_key;seenAccepted=true;return OK;
}
'''
values=[(False,'bad','100.00','BYPASS',0,'0.00',None),(True,'2026-01-01 00:00:00','0.00','ACCEPTED',1,'0.00',None),(True,'2025-02-30 00:00:00','1.00','BAD_TIME',0,'0.00',None),(True,'2025-12-31 23:59:59','1.00','TOO_OLD',0,'0.00',None),(True,'2026-01-02 00:00:00','-2.00','ACCEPTED',2,'-2.00',''),(False,'not-time','5.00','BYPASS',0,'-2.00',None),(True,None,None,'BAD_TIME',0,'-2.00',None),(True,'2026-1-3 00:00:00','2.00','BAD_TIME',0,'-2.00',None),(True,'2026-01-01 00:00:00',None,'ACCEPTED',3,'-2.00','claim5'),(True,'2026-01-04 12:00:00','3.00','ACCEPTED',4,'1.00','claim9')]
rows=[];expected=[]
for i,v in enumerate(values,1):
 request,text,amount,state,index,total,prev=v;row=dict(base(p,i),audit_requested=request,submitted_txt=text,claimed_amount=amount,claim_class='HEALTH');row['claim_key']='' if i==2 else 'claim'+str(i);rows.append(row);expected.append(dict(row,audit_state=state,audit_label=None if state=='BYPASS' else 'CLAIMS-R2',accepted_at=text if state=='ACCEPTED' else None,accepted_index=index,accepted_running=total,previous_claim_key=prev))
dictionary=[{'name':'auditEnabled','type':'boolean','value':True},{'name':'auditLabel','type':'string','value':'CLAIMS-R2'},{'name':'cutoffText','type':'string','value':'2026-01-01 00:00:00'}]
objects.append(make('T73',12,'Reformat (dictionary claims audit history)','Claims audit keeps history only for accepted requests','An insurer’s audit Reformat reads its run configuration from typed graph dictionary entries. It receives every claim, including records that opted out, and appends audit decisions without changing source attributes. The accepted sequence and monetary total belong only to this component execution, rather than an external sequence. Disabled auditing must be safe even when a timestamp or the otherwise unused cutoff text is malformed.',clauses,[('ClaimAuditSource',fields)],[('ClaimAuditDecision',out)],code,checks(clauses),forb('Must not parse timestamps/cutoff on a bypassed row or update history for nonaccepted rows.','Must not mutate dictionary configuration or use empty previous-key text as the unseen sentinel.','Must not drop bad dates, replace nullable money with a rejection or reorder by accepted_at.'),fix([rows],{'0':expected},dictionary_probes=[{'name':'disabled_invalid_cutoff','resources':{'dictionary':[{'name':'auditEnabled','type':'boolean','value':False},{'name':'auditLabel','type':'string','value':'OFF'},{'name':'cutoffText','type':'string','value':'NOT A DATE'}]},'inputs':[rows],'expected':{'0':[dict(r,audit_state='BYPASS',audit_label=None,accepted_at=None,accepted_index=0,accepted_running='0.00',previous_claim_key=None) for r in rows]}}]),resources=resources(dictionary=dictionary),change={'action':'replaced','reason':'Meter hash clone becomes dictionary-controlled claims audit, conditional parsing and accepted-only previous-record state.'},traps=['Run/row bypass before dictionary cutoff parsing','Accepted-only history with valid empty previous key','Null contribution and zero running total']))

if __name__=='__main__':write_shard('shard_t64_t73.json',objects)
