"""Independent module execution/persistence. No score or threshold changes.
Sharing dated raw rates is permitted; one module's status is NOT another gate.
"""
from types import SimpleNamespace
from core.input_contracts import number


def pending_smash(error):
    fields=('highest_board','highest_stock','break_rate','high_count','high_continue_count',
        'high_break_count','high_loss_count','first_board','second_board','third_board',
        'fourth_board','fifth_board','rate12','rate23','rate34','rate45','rate56')
    obj=SimpleNamespace(**{k:None for k in fields})
    obj.score=None;obj.state='待证据';obj.status='ERROR';obj.high_feedback='待证据';obj.rates={}
    obj.smash_detail={'status':'ERROR','error':error,'depends_on_emotion_score':False}
    return obj


def calculate_independent_modules(data, context, *, smash_fn=None, emotion_fn=None, overlay_fn=None):
    statuses={}
    try:
        if smash_fn is None:
            from analytics.smash_engine import calculate_smash
            smash_fn = calculate_smash
        if overlay_fn is None:
            from market_pipeline import overlay_smash
            overlay_fn = overlay_smash
        stats=getattr(data,'scope_stat_frames',{})
        smash=smash_fn(stats.get('limit_up',data.limit_up),
              data.previous_limit_up,stats.get('open_board',data.open_board))
        overlay_fn(smash,context)
        statuses['smash']={'status':'VALID' if number(smash.score) is not None else 'DATA_PENDING',
             'depends_on_emotion_score':False,'formula_function':'smash_dynamic.score',
             'formula_version':'5535_SMASH_DYNAMIC_DIV4_V1','formula_changed_by_user_approval':True}
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)
        smash=pending_smash(error)
        statuses['smash']={'status':'ERROR','error':error,'depends_on_emotion_score':False}
    try:
        if emotion_fn is None:
            from analytics.emotion_engine import calculate_emotion
            emotion_fn = calculate_emotion
        high=context['high_board_fail_rate']
        # Source high-loss count is shared raw input, not the SmashResult status/score.
        high_loss=high.get('numerator') if high.get('status')=='VALID' else None
        # Missing breadth is evidence-pending, never a neutral 0/0 substitute.
        # A validated historical aggregate is supplied by the persisted breadth
        # fact when available; otherwise the emotion module remains pending.
        br=context.get('breadth') or {}
        bu=br.get('up'); bd=br.get('down')
        emotion=emotion_fn(limit_up_count=context['counts']['up'],
           highest_board=context['highest_board']['value'],rate12=context['promotions']['1']['value'],
           yesterday_rate=context['yesterday_performance']['value'],break_rate=context['failed_limitup_rate']['value'],
           high_loss_count=high_loss,up_count=bu,down_count=bd)
        emotion.yesterday_performance=context['yesterday_performance']
        statuses['emotion']={'status':getattr(emotion,'status','DATA_PENDING'),
                             'depends_on_smash_score':False,'formula_changed':False}
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)
        emotion=SimpleNamespace(score=None,status='ERROR',cycle_stage='待证据',height_stage='待证据',
              detail={'error':error},missing_fields=['EMOTION_MODULE_ERROR'],
              yesterday_performance=context.get('yesterday_performance',{}))
        statuses['emotion']={'status':'ERROR','error':error,'depends_on_smash_score':False}
    return smash,emotion,statuses


def save_independent_history(data, context, smash, emotion, statuses, *, manager=None):
    warnings=[];state={};history=[]
    if manager is None:
        try:import history_manager as manager
        except Exception as exc:
            return [],{'emotion':'HISTORY_DEPENDENCY_ERROR','smash':'HISTORY_DEPENDENCY_ERROR'},[
                {'component':'history_manager','status':'ERROR','error':str(exc)}]
    jobs={
       'emotion':('save_history',{'date':data.date,'emotion_score':emotion.score,
         'limit_up_count':context['counts']['up'],'limit_down_count':context['counts']['down'],
         'open_board_rate':context['failed_limitup_rate']['value'],
         'break_rate':context['high_board_fail_rate']['value'],'highest_board':context['highest_board']['value'],
         'rate_12':context['promotions']['1']['value'],'rate_23':context['promotions']['2']['value'],
         'cycle_stage':getattr(emotion,'cycle_stage',None),'height_stage':getattr(emotion,'height_stage',None),
         'rule_version':context['rule_version']}),
       'smash':('save_smash_history',{'date':data.date,'smash_score':smash.score,
         'highest_board':getattr(smash,'highest_board',None),'highest_stock':getattr(smash,'highest_stock',None),
         **{'rate_'+str(k)+str(k+1):context['promotions'][str(k)]['value'] for k in range(2,6)}})}
    for key,(fn,record) in jobs.items():
        if statuses.get(key,{}).get('status')!='VALID' or number(record.get(key+'_score')) is None:
            state[key]='NOT_WRITTEN_OWN_INPUT_PENDING';continue
        try:
            getattr(manager,fn)(record);state[key]='WRITTEN'
        except Exception as exc:
            state[key]='ERROR';warnings.append({'component':key+'_history','status':'ERROR','error':str(exc)})
    try:history=manager.load_history()
    except Exception as exc:warnings.append({'component':'history_read','status':'ERROR','error':str(exc)})
    return history,state,warnings
