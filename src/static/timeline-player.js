import {clipAtTime,totalDuration} from './timeline-state.js';

// Preview is sequential HTML video playback; final frame-accurate cuts are exported by FFmpeg.
export class SequencePlayer {
  constructor(video,{onTime=()=>{},onSelect=()=>{},onError=()=>{},onPlayback=()=>{}}={}) {
    Object.assign(this,{video,onTime,onSelect,onError,onPlayback});
    this.clips=[]; this.index=-1; this.sequenceMode=false; this.advancing=false;
    video.addEventListener('timeupdate',()=>this.tick());
    video.addEventListener('ended',()=>this.finishClip());
    video.addEventListener('seeking',()=>this.clampSeek());
    video.addEventListener('play',()=>{this.clampSeek();this.onPlayback(true);});
    video.addEventListener('pause',()=>this.onPlayback(false));
    video.addEventListener('error',()=>{
      if (!this.clips.length || !video.getAttribute('src')) return;
      this.sequenceMode=false; this.advancing=false;
      this.onError('This clip could not be played. Reload the sequence to check its media.');
    });
  }
  setClips(clips,selectedId) {
    this.video.pause(); this.sequenceMode=false; this.clips=clips;
    if (!clips.length) {
      this.index=-1; this.video.removeAttribute('src'); this.video.load(); this.onTime(0,0); return;
    }
    const index=clips.findIndex(clip=>clip.clip_id===selectedId);
    this.select(index<0?0:index,undefined,false);
  }
  select(index,time,play=false) {
    const clip=this.clips[index]; if (!clip) return;
    this.advancing=true; this.video.pause(); this.index=index;
    const target=time ?? clip.in_frame/clip.fps;
    const ready=()=>{
      if (this.clips[this.index]?.clip_id!==clip.clip_id) return;
      this.video.currentTime=Math.max(clip.in_frame/clip.fps,
        Math.min(target,(clip.out_frame-.25)/clip.fps));
      this.advancing=false; this.tick();
      if (play) this.video.play().catch(()=>this.onError('Playback was paused by the browser. Use the video Play control.'));
    };
    this.video.onloadedmetadata=ready;
    if (this.video.getAttribute('src')===clip.media_url && this.video.readyState>=1) ready();
    else { this.video.src=clip.media_url; this.video.load(); }
    this.onSelect(clip);
  }
  playSequence() {
    if (!this.clips.length) return;
    if (this.sequenceMode && !this.video.paused) {this.video.pause();return;}
    const resume=this.sequenceMode && this.index>=0;
    this.sequenceMode=true;
    this.select(resume?this.index:0,resume?this.video.currentTime:undefined,true);
  }
  seek(time) {
    const position=clipAtTime(this.clips,time); if (!position) return;
    const playing=!this.video.paused;
    this.select(position.index,position.sourceTime,playing);
  }
  clampSeek() {
    const clip=this.clips[this.index];
    if (!clip || this.advancing || !Number.isFinite(this.video.currentTime)) return;
    const target=Math.max(clip.in_frame/clip.fps,Math.min(this.video.currentTime,(clip.out_frame-.25)/clip.fps));
    if (this.video.currentTime!==target) this.video.currentTime=target;
  }
  tick() {
    const clip=this.clips[this.index]; if (!clip || this.advancing) return;
    if (this.video.currentTime<clip.in_frame/clip.fps) this.video.currentTime=clip.in_frame/clip.fps;
    const before=totalDuration(this.clips.slice(0,this.index));
    const within=Math.max(0,Math.min(this.video.currentTime-clip.in_frame/clip.fps,
      (clip.out_frame-clip.in_frame)/clip.fps));
    this.onTime(before+within,totalDuration(this.clips));
    if (!this.video.paused && this.video.currentTime>=clip.out_frame/clip.fps-.25/clip.fps) this.finishClip();
  }
  finishClip() {
    const clip=this.clips[this.index]; if (!clip || this.advancing) return;
    if (this.sequenceMode && this.index+1<this.clips.length) this.select(this.index+1,undefined,true);
    else {
      this.video.pause(); this.sequenceMode=false;
      this.onTime(totalDuration(this.clips.slice(0,this.index+1)),totalDuration(this.clips));
    }
  }
  choose(id) {
    this.sequenceMode=false;this.select(this.clips.findIndex(clip=>clip.clip_id===id));
  }
}
