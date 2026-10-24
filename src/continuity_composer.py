"""Read-only native duration/capability projection for the shared composer."""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from typing import Annotated, Literal, cast
from continuable_take import get_validated_family
from h3_av_state import state_from_family, child_state, tail_fits
from h3_native_boundaries import prepare_operation, source_pin, NativeBoundaryError
from continuity_pipeline import _anchor_ids

Identifier=Annotated[str|None,Query(pattern=r'^[0-9a-f]{32}$',min_length=32,max_length=32)]

class CapabilityError(ValueError):
    def __init__(self, code, message):
        self.code=code
        super().__init__(message)

def operation_options(work,mode,take_id=None,second_take_id=None):
    """Read states once; never restage, upload, refine, submit or mutate files."""
    if mode=='root':
        from continuity_root_pipeline import root_state
        project=lambda raw:root_state(raw)
        geometry=None
    else:
        ids=(take_id,second_take_id) if mode=='bridge' else (take_id,)
        _anchor_ids(mode,ids)
        ids=cast(tuple[str,...],ids)
        families=[get_validated_family(work,id) for id in ids]
        contexts=[f.artifacts.to_manifest()['context'] for f in families]
        geometry={k:contexts[0][k] for k in ('width','height')}
        if any((c['width'],c['height'],c['fps'])!=(geometry['width'],geometry['height'],24) for c in contexts):
            raise CapabilityError('geometry_mismatch','These takes need matching picture sizes and 24 fps timing. Choose matching anchors.')
        if mode=='bridge' and (not all(c.get('self_id') for c in contexts)
                              or contexts[0]['self_id']==contexts[1]['self_id']):
            raise ValueError('Choose two distinct native sources.')
        try:
            measured=tuple(state_from_family(f) for f in families)
            if any(s is None for s in measured):raise ValueError('Missing timing')
        except (ValueError,OSError) as exc:
            raise CapabilityError('timing_unavailable','Saved timing is unavailable. Choose another take or start a new independent take.') from exc
        states=tuple(s for s in measured if s is not None)
        if mode!='prepend':source_pin(states[0],'tail','before')
        if mode!='forward':source_pin(states[-1],'head','after')
        project=(lambda raw:child_state(states[0],raw)) if mode=='forward' else (
            lambda raw:prepare_operation(mode,states,raw).child)
    options=[];codes=set()
    for raw in range(5,3601,17):
        try:
            state=project(raw)
            if tail_fits(state):options.append({'raw_frames':raw,'seconds':state.delivered_frames/24})
        except NativeBoundaryError as exc:codes.add(exc.code)
        except ValueError:continue
    code=None if options else ('audio_phase_conflict' if 'audio_phase_conflict' in codes else 'no_compatible_duration')
    reason=None if options else (str(NativeBoundaryError('audio_phase_conflict')) if code=='audio_phase_conflict' else
            'No compatible duration is available for this operation. Choose another anchor or start an independent take; originals are unchanged.')
    return {'available':bool(options),'verified':True,'mode':mode,'geometry':geometry,
            'duration_options':options,'reason_code':code,'reason':reason}


def create_router(get_work):
    router=APIRouter(prefix='/api/continuity',tags=['continuity'])
    @router.get('/composer-readiness')
    def readiness(mode:Literal['root','forward','prepend','bridge'],take_id:Identifier=None,second_take_id:Identifier=None):
        try:
            result=operation_options(get_work(),mode,take_id,second_take_id)
            if mode=='root':
                from readiness import _target_object_info
                try:
                    info=_target_object_info({'reference':{'class_type':'MiniMaxH3ReferenceToVideo','inputs':{}}})
                except (ValueError,OSError) as exc:
                    raise CapabilityError('target_unavailable','The compute target could not be checked. Reconnect the target and retry; nothing was submitted.') from exc
                inputs=info.get('MiniMaxH3ReferenceToVideo',{}).get('input',{})
                spec={**inputs.get('required',{}),**inputs.get('optional',{})}.get('ref_images',[])
                if spec and spec[0]=='COMFY_AUTOGROW_V3':
                    result['reference_limit']=spec[1]['template']['max']
        except (NativeBoundaryError,CapabilityError) as exc:
            result={'available':False,'verified':isinstance(exc,NativeBoundaryError),'mode':mode,'geometry':None,
                    'duration_options':[],'reason_code':exc.code,'reason':str(exc)}
        except (ValueError,OSError):
            result={'available':False,'verified':False,'mode':mode,'geometry':None,
                    'duration_options':[],'reason_code':'state_unverified','reason':'These saved anchors could not be used for this operation. Choose another position; nothing was submitted.'}
        return JSONResponse(result,headers={'Cache-Control':'private, no-store'})
    return router
