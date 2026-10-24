"""Read-only native duration/capability projection for the shared composer."""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from typing import Annotated, Literal, cast
from continuable_take import get_validated_family
from h3_av_state import state_from_family, child_state, tail_fits
from h3_native_boundaries import prepare_operation
from continuity_pipeline import _anchor_ids

Identifier=Annotated[str|None,Query(pattern=r'^[0-9a-f]{32}$',min_length=32,max_length=32)]

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
            raise ValueError('These takes need matching picture sizes and 24 fps timing.')
        if mode=='bridge' and (not all(c.get('self_id') for c in contexts)
                              or contexts[0]['self_id']==contexts[1]['self_id']):
            raise ValueError('Choose two distinct native sources.')
        measured=tuple(state_from_family(f) for f in families)
        if any(s is None for s in measured):raise ValueError('Saved timing is unavailable.')
        states=tuple(s for s in measured if s is not None)
        project=(lambda raw:child_state(states[0],raw)) if mode=='forward' else (
            lambda raw:prepare_operation(mode,states,raw).child)
    options=[]
    for raw in range(5,3601,17):
        try:
            state=project(raw)
            if tail_fits(state):options.append({'raw_frames':raw,'seconds':state.delivered_frames/24})
        except ValueError:continue
    return {'available':bool(options),'verified':True,'mode':mode,'geometry':geometry,
            'duration_options':options,'reason':None if options else
            'The saved beginning or audio timing cannot support this operation. Choose another anchor; original takes are unchanged.'}


def create_router(get_work):
    router=APIRouter(prefix='/api/continuity',tags=['continuity'])
    @router.get('/composer-readiness')
    def readiness(mode:Literal['root','forward','prepend','bridge'],take_id:Identifier=None,second_take_id:Identifier=None):
        try:
            result=operation_options(get_work(),mode,take_id,second_take_id)
            if mode=='root':
                from readiness import _target_object_info
                info=_target_object_info({'reference':{'class_type':'MiniMaxH3ReferenceToVideo','inputs':{}}})
                inputs=info.get('MiniMaxH3ReferenceToVideo',{}).get('input',{})
                spec={**inputs.get('required',{}),**inputs.get('optional',{})}.get('ref_images',[])
                if spec and spec[0]=='COMFY_AUTOGROW_V3':
                    result['reference_limit']=spec[1]['template']['max']
        except (ValueError,OSError):
            result={'available':False,'verified':False,'mode':mode,'geometry':None,
                    'duration_options':[],'reason':'These saved anchors could not be used for this operation. Choose another position; nothing was submitted.'}
        return JSONResponse(result,headers={'Cache-Control':'private, no-store'})
    return router
