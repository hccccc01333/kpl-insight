/* Full-viewport world: flowing 3D lanes, surface light, streaming particles and scroll camera. */
const root = document.documentElement;
root.classList.add('world-site');
const backdrop = document.createElement('div');
backdrop.className = 'world-backdrop';
backdrop.setAttribute('aria-hidden', 'true');
backdrop.innerHTML = '<canvas class="world-canvas"></canvas><div class="world-vignette"></div>';
document.body.prepend(backdrop);
const control = document.createElement('button');
control.className = 'world-motion'; control.type = 'button';
control.setAttribute('aria-label', '切换整页动态场景');
document.body.append(control);
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const explicit = new URLSearchParams(location.search).get('motion');
let choice=explicit==='on'||explicit==='off'?explicit:null;
try { if(choice)sessionStorage.setItem('kpl-world-motion',choice);else choice=sessionStorage.getItem('kpl-world-motion'); } catch {}
let active = choice === 'on' || (choice !== 'off' && !reduced.matches);
let requestFrame = () => {};
function label() { control.textContent = active ? 'Ⅱ 暂停场景' : '▷ 开启沉浸动效'; control.setAttribute('aria-pressed', String(active)); }
control.addEventListener('click', () => { active = !active; choice=active?'on':'off';try{sessionStorage.setItem('kpl-world-motion',choice);}catch{}label();requestFrame(); });
reduced.addEventListener('change', () => { if(!choice)active = !reduced.matches; label(); requestFrame(); });
label();

// UI movement follows the same scroll and pointer context as the world.
let mx=0,my=0,scroll=scrollY,section=0;
const home=!!document.querySelector('.world-hero');
const sections=[...document.querySelectorAll('main .block, .world-hero')];
const revealObserver=new IntersectionObserver(entries=>{
  for(const entry of entries)if(entry.isIntersecting){entry.target.classList.add('world-visible');revealObserver.unobserve(entry.target);}
},{threshold:.06});
for(const block of sections){block.classList.add('world-reveal');revealObserver.observe(block);}
window.addEventListener('pointermove',e=>{mx=e.clientX/innerWidth*2-1;my=e.clientY/innerHeight*2-1;requestFrame();},{passive:true});
window.addEventListener('scroll',()=>{scroll=scrollY;section=Math.min(5,scroll/innerHeight);requestFrame();},{passive:true});
document.querySelectorAll('.world-scenes button').forEach(button=>button.addEventListener('click',()=>{
  const target=document.querySelector(button.dataset.target);if(target)target.scrollIntoView({behavior:reduced.matches?'instant':'smooth',block:'start'});
}));
import('./vendor/three.module-0.170.0.js').then(build).catch(fallback);
function fallback(error){root.dataset.worldRenderer='css';root.dataset.worldError=error?.message||'context lost';backdrop.classList.add('world-fallback');}

function build(T){
  const canvas=backdrop.querySelector('canvas');
  const renderer=new T.WebGLRenderer({canvas,alpha:false,antialias:true,powerPreference:'default'});
  renderer.setPixelRatio(Math.min(devicePixelRatio||1,innerWidth<600?1.25:1.5));
  renderer.setClearColor(0x06081c,1);
  renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1.1;
  const scene=new T.Scene();
  const camera=new T.PerspectiveCamera(52,innerWidth/innerHeight,.1,100);
  camera.position.set(0,0,12);
  const world=new T.Group();scene.add(world);
  const uniforms={uTime:{value:0},uPointer:{value:new T.Vector2()},uScroll:{value:0},uResolution:{value:new T.Vector2(innerWidth,innerHeight)}};
  // A screen-filling animated chromatic atmosphere, independent of individual meshes.
  const background=new T.Mesh(new T.PlaneGeometry(2,2),new T.ShaderMaterial({
    depthTest:false,depthWrite:false,uniforms,
    vertexShader:`varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,1.,1.);}`,
    fragmentShader:`varying vec2 vUv;uniform float uTime;uniform float uScroll;uniform vec2 uPointer;uniform vec2 uResolution;
    void main(){
      vec2 p=vUv;vec2 q=p+uPointer*.018;
      float blue=exp(-3.8*length((q-vec2(.12+.10*sin(uTime*.15+uScroll),.58))*vec2(1.1,1.)));
      float pink=exp(-4.0*length((q-vec2(.9,.62+.15*sin(uTime*.12)))*vec2(.9,1.)));
      float amber=exp(-6.0*length(q-vec2(.68+.15*sin(uTime*.1),.04)));
      vec3 col=vec3(.012,.018,.055)+blue*vec3(.01,.075,.22)+pink*vec3(.18,.012,.16)+amber*vec3(.25,.07,.015);
      float haze=sin(p.x*7.+p.y*5.+uTime*.15+sin(p.y*5.-uTime*.1))*0.5+0.5;
      col+=haze*.025*vec3(.2,.5,.9);
      float grain=fract(sin(dot(gl_FragCoord.xy,vec2(12.9898,78.233)))*43758.5453);
      col+=(grain-.5)*.012;
      gl_FragColor=vec4(col,1.);
    }`
  }));background.frustumCulled=false;background.renderOrder=-10;scene.add(background);

  // Broad, twisting lane ribbons stretch beyond every viewport edge.
  function path(t,lane){
    const a=t*Math.PI*2;
    return new T.Vector3(Math.sin(a+lane*.7)*9.8,Math.cos(a+lane*.92)*4.8,Math.sin(a*2+lane)*3.2-2.7);
  }
  function ribbonGeometry(lane){
    const pos=[],uv=[],indices=[],steps=220,rows=8;
    for(let i=0;i<=steps;i++){
      const t=i/steps,p=path(t,lane),forward=path(t+.001,lane).sub(p).normalize();
      const normal=new T.Vector3(0,0,1).cross(forward).normalize();
      const binormal=new T.Vector3().crossVectors(forward,normal).normalize();
      const twist=Math.sin(t*Math.PI*4+lane)*1.6+t*Math.PI*2;
      const wing=normal.multiplyScalar(Math.cos(twist)).add(binormal.multiplyScalar(Math.sin(twist)));
      const width=(.45+.38*Math.sin(t*Math.PI*4+lane)**2)*(lane===0?1.35:1);
      for(let j=0;j<=rows;j++){
        const v=j/rows-.5;const point=p.clone().addScaledVector(wing,v*width*2);
        pos.push(...point.toArray());uv.push(t,j/rows);
        if(i<steps&&j<rows){const k=i*(rows+1)+j;indices.push(k,k+rows+1,k+1,k+1,k+rows+1,k+rows+2);}
      }
    }
    const g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute(pos,3));g.setAttribute('uv',new T.Float32BufferAttribute(uv,2));g.setIndex(indices);g.computeVertexNormals();return g;
  }
  const colors=[[0x1ce9ff,0x2452ff],[0xff3f91,0xff842d],[0x9a57ff,0xff35b8],[0xffbc46,0xff5052]];
  const ribbons=[];
  for(let lane=0;lane<4;lane++){
    const material=new T.ShaderMaterial({side:T.DoubleSide,transparent:true,depthWrite:false,uniforms:{...uniforms,uLane:{value:lane},uColorA:{value:new T.Color(colors[lane][0])},uColorB:{value:new T.Color(colors[lane][1])}},
      vertexShader:`varying vec2 vUv;varying vec3 vNormal;varying vec3 vView;uniform float uTime;uniform float uLane;uniform float uScroll;
      void main(){vUv=uv;vec3 p=position;p.y+=sin(p.x*.38+uTime*.25+uLane)*.35;p.z+=sin(p.y*.55+uTime*.2)*.35;
      vec4 mv=modelViewMatrix*vec4(p,1.);vView=-mv.xyz;vNormal=normalize(normalMatrix*normal);gl_Position=projectionMatrix*mv;}`,
      fragmentShader:`varying vec2 vUv;varying vec3 vNormal;varying vec3 vView;uniform float uTime;uniform float uLane;uniform vec3 uColorA;uniform vec3 uColorB;
      void main(){float edge=pow(abs(vUv.y-.5)*2.,5.);float fresnel=pow(1.-abs(dot(normalize(vNormal),normalize(vView))),2.);
      float streak=pow(.5+.5*sin(vUv.x*94.24778-uTime*2.+uLane),12.);
      float threads=pow(.5+.5*sin(vUv.y*120.),18.);
      float flow=.5+.5*sin(vUv.x*12.56637-uTime*.45+uLane);
      vec3 col=mix(uColorA,uColorB,flow);col*=.32+edge*1.6+fresnel*.9+streak*.45+threads*.13;
      float alpha=.37+edge*.5+fresnel*.25;
      gl_FragColor=vec4(col,alpha);}`
    });
    const ribbon=new T.Mesh(ribbonGeometry(lane),material);ribbon.frustumCulled=false;world.add(ribbon);ribbons.push(ribbon);
  }
  // The particle highways use real xyz curves; camera movement changes their depth ordering.
  const mobile=innerWidth<600;const n=mobile?6500:15000;
  const progress=new Float32Array(n),laneIds=new Float32Array(n),seeds=new Float32Array(n*3),dummy=new Float32Array(n*3);
  for(let i=0;i<n;i++){progress[i]=Math.random();laneIds[i]=i%4;seeds[i*3]=Math.random();seeds[i*3+1]=Math.random();seeds[i*3+2]=Math.random();}
  const pg=new T.BufferGeometry();pg.setAttribute('position',new T.BufferAttribute(dummy,3));pg.setAttribute('aProgress',new T.BufferAttribute(progress,1));pg.setAttribute('aLane',new T.BufferAttribute(laneIds,1));pg.setAttribute('aSeed',new T.BufferAttribute(seeds,3));
  const points=new T.Points(pg,new T.ShaderMaterial({transparent:true,depthWrite:false,blending:T.AdditiveBlending,uniforms:{...uniforms,uDpr:{value:renderer.getPixelRatio()}},
    vertexShader:`attribute float aProgress;attribute float aLane;attribute vec3 aSeed;uniform float uTime;uniform float uDpr;varying vec3 vColor;varying float vAlpha;
    void main(){float t=fract(aProgress+uTime*(.008+aSeed.x*.008));float a=t*6.283185;
      vec3 p=vec3(sin(a+aLane*.7)*9.8,cos(a+aLane*.92)*4.8,sin(a*2.+aLane)*3.2-2.7);
      p+=(aSeed-.5)*vec3(.9,1.1,1.6);p.y+=sin(p.x*.38+uTime*.25+aLane)*.35;
      vec4 mv=modelViewMatrix*vec4(p,1.);gl_Position=projectionMatrix*mv;
      gl_PointSize=min(5.,(12.+aSeed.y*23.)*uDpr/max(2.,-mv.z));
      if(aLane<.5)vColor=vec3(.1,.8,1.);else if(aLane<1.5)vColor=vec3(1.,.22,.4);else if(aLane<2.5)vColor=vec3(.67,.3,1.);else vColor=vec3(1.,.65,.22);
      vAlpha=.35+aSeed.z*.65;}`,
    fragmentShader:`varying vec3 vColor;varying float vAlpha;void main(){float d=length(gl_PointCoord-.5);if(d>.5)discard;float a=pow(1.-d*2.,1.5);gl_FragColor=vec4(vColor*1.5,a*vAlpha);}`
  }));points.frustumCulled=false;world.add(points);
  // Thin perspective lanes suggest the battlefield, rather than an isolated display object.
  const floor=new T.Group();world.add(floor);
  for(let j=-12;j<=12;j++){
    const pts=[];for(let i=0;i<=70;i++){const z=-20+i*.5;pts.push(new T.Vector3(j*1.6+Math.sin(z*.12)*1.7,-5.1+Math.cos(z*.12)*.7,z));}
    floor.add(new T.Line(new T.BufferGeometry().setFromPoints(pts),new T.LineBasicMaterial({color:j%3===0?0x467ccf:0x273a73,transparent:true,opacity:j%3===0?.24:.11})));
  }
  let frame=0,last=0,time=2,px=0,py=0,camScroll=0;
  let samples=0,spent=0,scaled=false;
  function render(now){
    frame=0;if(document.hidden)return;
    const dt=last?Math.min((now-last)/1000,.06):1/60;last=now;
    if(active)time+=dt;
    const ease=reduced.matches?1:1-Math.exp(-dt*4);
    px+=(mx-px)*ease;py+=(my-py)*ease;camScroll+=(section-camScroll)*ease;
    uniforms.uTime.value=time;uniforms.uPointer.value.set(px,py);uniforms.uScroll.value=camScroll;
    world.rotation.y=px*.12+camScroll*.12+(active?Math.sin(time*.08)*.08:0);
    world.rotation.x=py*.06+Math.sin(camScroll*.7)*.16;
    world.position.y=Math.sin(camScroll*.9)*.8;
    camera.position.x=px*.42+Math.sin(camScroll*.6)*1.2;
    camera.position.y=-py*.24+Math.sin(camScroll*.5)*.5;
    camera.position.z=12-Math.min(camScroll,3)*.5;
    camera.lookAt(0,0,-2);
    renderer.render(scene,camera);
    root.dataset.worldMotion=active?'running':'paused';
    root.dataset.worldFrame=String(samples++);
    root.dataset.worldCamera=[camera.position.x,camera.position.y,camera.position.z].map(v=>v.toFixed(3)).join(',');
    root.style.setProperty('--world-mx',px.toFixed(3));root.style.setProperty('--world-my',py.toFixed(3));
    root.style.setProperty('--world-scroll',camScroll.toFixed(3));
    if(samples>30&&!scaled){spent+=dt;if(samples>=110){if(spent/80>.035){renderer.setPixelRatio(1);resize();}scaled=true;}}
    if(active||Math.abs(px-mx)>.001||Math.abs(py-my)>.001||Math.abs(camScroll-section)>.001)request();
  }
  function request(){if(!frame&&!document.hidden)frame=requestAnimationFrame(render);}
  requestFrame=request;
  function resize(){renderer.setSize(innerWidth,innerHeight,false);camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();uniforms.uResolution.value.set(innerWidth,innerHeight);request();}
  window.addEventListener('resize',resize,{passive:true});
  document.addEventListener('visibilitychange',()=>{last=0;if(document.hidden){cancelAnimationFrame(frame);frame=0;}else request();});
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();cancelAnimationFrame(frame);frame=0;fallback();});
  canvas.addEventListener('webglcontextrestored',()=>{root.dataset.worldRenderer='webgl';backdrop.classList.remove('world-fallback');resize();request();});
  root.dataset.worldRenderer='webgl';root.dataset.worldParticles=String(n);
  resize();request();
}
