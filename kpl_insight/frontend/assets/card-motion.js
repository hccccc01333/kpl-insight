/* Shared interaction layer. Existing nodes, links, filters and datasets stay in place. */
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
const fine=matchMedia('(hover: hover) and (pointer: fine)');
const cardSelector='.tcard,.player,.hcard,.rp-pick,.champ,.day-group,.hn-lane,.hn-team,.pick-card,.combo-card,.entry,.studio-card';
const surfaceSelector='.panel,.bp2-panel,.cmp-radar,.sr-card,.rp-story,.sb-kpi,.studio-surface,.studio-workbench';
const gridSelector='.team-grid,.player-grid,.hero-grid:not(.mini),.hn-lanes,.pick-grid,.replay-picks,.entry-grid';
const nativeSelector='.day-rail,.champ-strip,.season-rail,.stage-track,.tm-rail,.studio-actions-scroll';
const tabsSelector='.seg,.rp-tabs,.hn-kind,.studio-tabs';
const known=new WeakSet(),groups=new WeakMap(),tabs=new WeakSet();
let sequence=0,tilt=null,tiltFrame=0;
const animated=()=>!reduced.matches;
const easing='cubic-bezier(.2,.7,.2,1)';
const reveal=new IntersectionObserver(entries=>{
  let index=0;
  for(const entry of entries){
    if(!entry.isIntersecting)continue;
    reveal.unobserve(entry.target);
    if(animated()){
      entry.target.animate([{opacity:.35,translate:'0 20px'},{opacity:1,translate:'0 0'}],{duration:480,delay:Math.min(index++*36,180),easing});
      entry.target.querySelectorAll('.pwbar .pb i,.minibar i,.pred-row .bar i').forEach((bar,i)=>{
        bar.animate([{scale:'0 1'},{scale:'1 1'}],{duration:650,delay:Math.min(i*45,240),easing});
      });
    }
  }
},{threshold:.08,rootMargin:'0px 0px 25px 0px'});

function all(node,selector){const result=[];if(node.nodeType!==1)return result;if(node.matches(selector))result.push(node);result.push(...node.querySelectorAll(selector));return result;}
function enhance(node){
  for(const card of all(node,cardSelector+','+surfaceSelector)){
    if(known.has(card))continue;known.add(card);
    card.classList.add(card.matches(cardSelector)?'motion-card':'motion-surface');
    reveal.observe(card);
  }
  for(const grid of all(node,gridSelector))collection(grid,false);
  for(const rail of all(node,nativeSelector))collection(rail,true);
  for(const tab of all(node,tabsSelector))enhanceTabs(tab);
}

function collection(el,native){
  if(groups.has(el))return groups.get(el).update();
  if(!el.id)el.id='motion-collection-'+(++sequence);
  const label=el.matches('.team-grid')?'战队':el.matches('.player-grid')?'选手':el.matches('.hero-grid')?'英雄':el.matches('.hn-lanes')?'分路荣誉':el.matches('.champ-strip')?'历届冠军':el.matches('.day-rail')?'比赛日':el.matches('.replay-picks,.pick-grid')?'复盘':el.matches('.entry-grid')?'分析工具':'卡片';
  const toolbar=document.createElement('div');toolbar.className='motion-browse';
  toolbar.setAttribute('role','group');toolbar.setAttribute('aria-label',label+'展示方式与浏览');
  const modeButtons=native?'<span class="motion-browse-title">'+label+' <small>左右滑动浏览</small></span>':'<div class="motion-view"><button type="button" data-view="grid" aria-pressed="true">网格</button><button type="button" data-view="rail" aria-pressed="false">横滑</button></div>';
  toolbar.innerHTML=modeButtons+'<div class="motion-browse-right"><span class="motion-position" aria-live="polite" aria-atomic="true"></span><span class="motion-track" aria-hidden="true"><i></i></span><button type="button" class="motion-prev" aria-label="向前浏览'+label+'" aria-controls="'+el.id+'">←</button><button type="button" class="motion-next" aria-label="向后浏览'+label+'" aria-controls="'+el.id+'">→</button></div>';
  el.before(toolbar);
  const prev=toolbar.querySelector('.motion-prev'),next=toolbar.querySelector('.motion-next'),position=toolbar.querySelector('.motion-position'),progress=toolbar.querySelector('.motion-track i');
  const gridButton=toolbar.querySelector('[data-view="grid"]'),railButton=toolbar.querySelector('[data-view="rail"]');
  let rail=native,scrollFrame=0,lastText='',drag=null,suppress=false;
  const children=()=>[...el.children].filter(c=>!c.matches('.empty-tip,.hn-muted'));
  el.classList.add('motion-collection');
  if(native)el.classList.add('motion-rail');
  if(!el.hasAttribute('tabindex'))el.tabIndex=0;
  if(!el.hasAttribute('aria-label'))el.setAttribute('aria-label',label+'卡片，横滑模式下可使用左右方向键浏览');
  function update(){
    scrollFrame=0;const items=children(),max=Math.max(0,el.scrollWidth-el.clientWidth);
    const overflowing=rail&&max>4;
    toolbar.hidden=items.length<2;
    prev.hidden=next.hidden=!rail;
    progress.parentElement.hidden=!rail;
    prev.disabled=!overflowing||el.scrollLeft<3;
    next.disabled=!overflowing||el.scrollLeft>=max-3;
    let current=0;
    if(rail){
      const left=el.getBoundingClientRect().left;
      current=items.findIndex(c=>c.getBoundingClientRect().right>left+20);
      current=Math.max(0,current);
    }
    const text=rail?(current+1)+' / '+items.length:items.length+' 张卡片';
    if(text!==lastText){position.textContent=text;lastText=text;}
    progress.style.transform='scaleX('+(max?Math.max(.07,el.scrollLeft/max):1)+')';
    el.dataset.motionView=rail?'rail':'grid';
  }
  function schedule(){if(!scrollFrame)scrollFrame=requestAnimationFrame(update);}
  function setMode(value){
    rail=value==='rail';el.classList.toggle('motion-rail',rail);
    gridButton?.setAttribute('aria-pressed',String(!rail));railButton?.setAttribute('aria-pressed',String(rail));
    el.scrollLeft=0;
    if(animated())el.animate([{opacity:.45,translate:'0 8px'},{opacity:1,translate:'0 0'}],{duration:240,easing});
    update();
  }
  function advance(direction){
    const first=children()[0];const step=Math.max(first?first.getBoundingClientRect().width+14:200,el.clientWidth*.78);
    el.scrollBy({left:direction*step,behavior:animated()?'smooth':'instant'});
  }
  prev.addEventListener('click',()=>advance(-1));next.addEventListener('click',()=>advance(1));
  gridButton?.addEventListener('click',()=>setMode('grid'));railButton?.addEventListener('click',()=>setMode('rail'));
  el.addEventListener('scroll',schedule,{passive:true});
  el.addEventListener('keydown',e=>{
    if(!rail||e.target!==el)return;
    if(e.key==='ArrowRight'){e.preventDefault();advance(1);}else if(e.key==='ArrowLeft'){e.preventDefault();advance(-1);}
    else if(e.key==='Home'||e.key==='End'){e.preventDefault();el.scrollTo({left:e.key==='Home'?0:el.scrollWidth,behavior:animated()?'smooth':'instant'});}
  });
  // Native touch scrolling is left to the browser. Desktop drag starts only after intentional movement.
  el.addEventListener('pointerdown',e=>{
    suppress=false;
    if(!rail||e.pointerType!=='mouse'||e.button!==0||e.target.closest('button,input,select,textarea,summary'))return;
    drag={id:e.pointerId,x:e.clientX,y:e.clientY,left:el.scrollLeft,started:false};
  });
  el.addEventListener('pointermove',e=>{
    if(!drag||e.pointerId!==drag.id)return;
    const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
    if(!drag.started){if(Math.abs(dx)<8||Math.abs(dx)<Math.abs(dy))return;drag.started=true;el.setPointerCapture(e.pointerId);el.classList.add('motion-dragging');}
    e.preventDefault();suppress=true;el.scrollLeft=drag.left-dx;
  });
  function release(){drag=null;el.classList.remove('motion-dragging');}
  el.addEventListener('pointerup',release);el.addEventListener('pointercancel',release);el.addEventListener('lostpointercapture',release);
  el.addEventListener('pointerleave',()=>{if(drag&&!drag.started)release();});
  el.addEventListener('dragstart',e=>{if(rail)e.preventDefault();});
  el.addEventListener('click',e=>{if(suppress&&e.detail!==0){e.preventDefault();e.stopImmediatePropagation();suppress=false;}},true);
  new ResizeObserver(schedule).observe(el);
  const state={update:schedule};groups.set(el,state);update();return state;
}

function enhanceTabs(el){
  if(tabs.has(el))return;tabs.add(el);el.classList.add('motion-tabs');
  const update=()=>{
    const active=el.querySelector('button.on,button.active,button[aria-selected="true"]');
    if(!active||!active.offsetWidth){el.style.setProperty('--tab-opacity','0');return;}
    el.style.setProperty('--tab-left',active.offsetLeft+'px');el.style.setProperty('--tab-top',active.offsetTop+'px');
    el.style.setProperty('--tab-width',active.offsetWidth+'px');el.style.setProperty('--tab-height',active.offsetHeight+'px');el.style.setProperty('--tab-opacity','1');
  };
  new ResizeObserver(update).observe(el);
  new MutationObserver(update).observe(el,{subtree:true,attributes:true,attributeFilter:['class','aria-selected'],childList:true});
  update();
}

function setTilt(e){
  if(!fine.matches||!animated())return;
  const card=e.target.closest('.motion-card');if(!card||card.closest('.motion-dragging')||card.matches(':has(details[open])'))return;
  if(tilt&&tilt.card!==card)resetTilt();
  const box=card.getBoundingClientRect();tilt={card,x:(e.clientX-box.left)/box.width,y:(e.clientY-box.top)/box.height};
  if(!tiltFrame)tiltFrame=requestAnimationFrame(()=>{
    tiltFrame=0;if(!tilt)return;const {card,x,y}=tilt;
    card.style.setProperty('--card-rx',((.5-y)*3.6).toFixed(2)+'deg');card.style.setProperty('--card-ry',((x-.5)*4).toFixed(2)+'deg');
    card.style.setProperty('--card-x',(x*100).toFixed(1)+'%');card.style.setProperty('--card-y',(y*100).toFixed(1)+'%');
  });
}
function resetTilt(){if(tilt){tilt.card.style.setProperty('--card-rx','0deg');tilt.card.style.setProperty('--card-ry','0deg');tilt=null;}}
document.addEventListener('pointermove',setTilt,{passive:true});
document.addEventListener('pointerout',e=>{if(tilt&&!tilt.card.contains(e.relatedTarget))resetTilt();},{passive:true});
window.addEventListener('blur',resetTilt);reduced.addEventListener('change',resetTilt);

// Animate native details without replacing the summary or its accessible open state.
const detailStates=new WeakMap();
document.addEventListener('click',e=>{
  const summary=e.target.closest('summary');
  if(!summary||!summary.closest('main')||!animated()||e.defaultPrevented)return;
  const details=summary.parentElement;if(details.tagName!=='DETAILS')return;
  e.preventDefault();
  const previous=detailStates.get(details),desired=previous?!previous.desired:!details.open;
  const from=details.getBoundingClientRect().height;previous?.animation.cancel();
  const oldOverflow=details.style.overflow,oldHeight=details.style.height;
  details.style.height='';details.open=true;
  const to=desired?details.getBoundingClientRect().height:summary.getBoundingClientRect().height;
  details.style.overflow='hidden';
  const animation=details.animate([{height:from+'px'},{height:to+'px'}],{duration:260,easing});
  detailStates.set(details,{animation,desired});
  animation.onfinish=()=>{details.open=desired;details.style.height=oldHeight;details.style.overflow=oldOverflow;detailStates.delete(details);};
});

// A short surface transition clarifies tab changes while existing handlers own the actual selection.
document.addEventListener('click',e=>{
  if(!animated()||!e.target.closest('.motion-tabs button'))return;
  const main=e.target.closest('main')||document.querySelector('main');if(!main)return;
  requestAnimationFrame(()=>{
    const panels=[...main.querySelectorAll('.motion-surface')].filter(p=>p.getBoundingClientRect().height>0);
    panels.slice(0,6).forEach(p=>p.animate([{opacity:.65,translate:'0 7px'},{opacity:1,translate:'0 0'}],{duration:230,easing}));
  });
});

// Observe additions only: pointer CSS updates and each animation frame do not trigger rescans.
let mutationFrame=0;const pending=new Set();
new MutationObserver(records=>{
  for(const record of records){
    if(record.target instanceof Element){const group=record.target.closest('.motion-collection');if(group)groups.get(group)?.update();}
    for(const node of record.addedNodes)if(node.nodeType===1&&!node.matches('.motion-browse,.world-backdrop,.world-motion'))pending.add(node);
  }
  if(pending.size&&!mutationFrame)mutationFrame=requestAnimationFrame(()=>{mutationFrame=0;const added=[...pending];pending.clear();for(const node of added)if(node.isConnected)enhance(node);});
}).observe(document.body,{childList:true,subtree:true});
enhance(document.body);
document.documentElement.dataset.cardMotion='ready';
