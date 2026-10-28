/* Real, locally rendered trophy geometry, environment reflections and GPU particles.
   The model is an artistic reconstruction inspired by the KPL trophy, not an official asset. */
const hero = document.getElementById('arenaHero');
if (hero) import('./vendor/three.module-0.170.0.js').then(init).catch(showPoster);

function showPoster(error) {
  hero.classList.remove('arena-3d-ready');
  hero.dataset.renderer = 'poster';
  hero.dataset.motion = 'unavailable';
  hero.querySelector('.arena-toggle').hidden = true;
  hero.querySelector('.arena-burst').hidden = true;
  hero.querySelector('.arena-reset').hidden = true;
  hero.querySelector('.arena-hint').textContent = '奖杯艺术主视觉';
  hero.dataset.renderError = error?.message || 'WebGL context lost';
}

function init(T) {
  const canvas = hero.querySelector('.arena-webgl');
  const toggle = hero.querySelector('.arena-toggle');
  const burst = hero.querySelector('.arena-burst');
  const reset = hero.querySelector('.arena-reset');
  const hint = hero.querySelector('.arena-hint');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const renderer = new T.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'default' });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x090b0f, 0);
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.18;
  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(35, 1, .1, 60);
  camera.position.set(0, .35, 9.6);
  camera.lookAt(0, .05, 0);

  // A local studio environment provides real metallic reflections on every angle.
  const studio = new T.Scene();
  studio.background = new T.Color(0x151c28);
  function softbox(color, intensity, w, h, position) {
    const panel = new T.Mesh(new T.PlaneGeometry(w, h), new T.MeshBasicMaterial({ color, side: T.DoubleSide }));
    panel.material.color.multiplyScalar(intensity);
    panel.position.set(...position); panel.lookAt(0, 0, 0); studio.add(panel);
  }
  softbox(0xf1f6ff, 4, 3, 7, [-4, 3, 4]);
  softbox(0xffffff, 6, 1.3, 6, [3, 1, 3]);
  softbox(0x449eff, 5, 2, 7, [-4, 0, -1]);
  softbox(0xff405b, 4, 2, 6, [4, 0, -2]);
  softbox(0xdce9ff, 3, 6, 2, [0, 6, 0]);
  const pmrem = new T.PMREMGenerator(renderer);
  const environment = pmrem.fromScene(studio, .06, .1, 30);
  scene.environment = environment.texture;
  studio.traverse(o => { if (o.isMesh) { o.geometry.dispose(); o.material.dispose(); } });
  pmrem.dispose();
  scene.add(new T.HemisphereLight(0xd7e6ff, 0x10131a, 1.5));
  function light(color, intensity, x, y, z) {
    const l = new T.DirectionalLight(color, intensity); l.position.set(x, y, z); scene.add(l);
  }
  light(0xffffff, 3.5, -2, 5, 5); light(0x4e9dff, 4, -5, 0, 1); light(0xff3555, 3.8, 5, 1, -1);

  const trophy = new T.Group(); scene.add(trophy);
  const silver = new T.MeshPhysicalMaterial({ color: 0xc4cedc, metalness: 1, roughness: .22, clearcoat: .65, clearcoatRoughness: .19, envMapIntensity: 1.2 });
  const edge = new T.MeshPhysicalMaterial({ color: 0xe4ebf5, metalness: 1, roughness: .13, envMapIntensity: 1.4 });
  const dark = new T.MeshPhysicalMaterial({ color: 0x2e3a4e, metalness: .95, roughness: .3 });
  const ice = new T.MeshPhysicalMaterial({ color: 0x93bcdf, metalness: .8, roughness: .19, emissive: 0x102d4a, emissiveIntensity: .35 });
  function mesh(geometry, material = silver, position = [0, 0, 0]) {
    const m = new T.Mesh(geometry, material); m.position.set(...position); trophy.add(m); return m;
  }
  function lathe(profile, material = silver, segments = 96) {
    return mesh(new T.LatheGeometry(profile.map(p => new T.Vector2(...p)), segments), material);
  }
  function tube(points, radius, material = edge, segments = 80) {
    return mesh(new T.TubeGeometry(new T.CatmullRomCurve3(points.map(p => new T.Vector3(...p))), segments, radius, 10, false), material);
  }
  // Stepped podium and twisted stem.
  lathe([[0,-2.12],[.78,-2.12],[.86,-2.08],[.87,-1.99],[.8,-1.94],[.71,-1.9],[.65,-1.83],[.48,-1.78],[.35,-1.68],[.22,-1.55]], silver);
  lathe([[.78,-2.09],[.88,-2.07],[.88,-2.025],[.78,-2.01]], edge);
  lathe([[.22,-1.63],[.16,-1.4],[.145,-1.05],[.17,-.7],[.24,-.35],[.38,-.07]], dark);
  for (let strand = 0; strand < 3; strand++) {
    const pts = [];
    for (let j = 0; j <= 60; j++) {
      const t = j / 60, a = t * Math.PI * 1.28 + strand * Math.PI * 2 / 3;
      const r = .16 + Math.pow(t, 2) * .14;
      pts.push([Math.cos(a)*r, -1.68+t*1.68, Math.sin(a)*r]);
    }
    tube(pts, .085, strand === 1 ? edge : silver, 60);
  }
  // Hollow chalice, with an undulating petal rim and an actual inside surface.
  const profile = [[.28,-.12],[.43,.02],[.64,.29],[.83,.62],[1.02,1.03],[1.12,1.43],[1.16,1.73],[1.12,1.76],[1.07,1.42],[.96,1.04],[.77,.64],[.58,.32],[.39,.1],[.28,.06]];
  const bowl = lathe(profile, silver, 128);
  const bp = bowl.geometry.attributes.position;
  for (let i=0; i<bp.count; i++) {
    const y = bp.getY(i), angle = Math.atan2(bp.getZ(i), bp.getX(i));
    const ripple = Math.pow(Math.max(0,(y-.4)/1.4),3);
    bp.setY(i, y + Math.cos(angle*6)*.105*ripple);
  }
  bowl.geometry.computeVertexNormals();
  // Fine bright seams describe the cup curvature while it rotates.
  for (let rib = 0; rib < 12; rib++) {
    const a = rib*Math.PI/6, pts=[];
    for (const [r,y] of profile.slice(0,7)) pts.push([Math.sin(a)*(r+.012),y+Math.cos((Math.PI/2-a)*6)*.105*Math.pow(Math.max(0,(y-.4)/1.4),3),Math.cos(a)*(r+.012)]);
    tube(pts,.012,edge,38);
  }
  // Two independent dragon handles. Their silhouettes visibly overlap the bowl in depth.
  for (const side of [-1,1]) {
    tube([[side*.43,.03,0],[side*1.02,.32,-.06],[side*1.66,.73,-.04],[side*1.88,1.2,0],[side*1.75,1.67,.02],[side*1.35,1.83,.02],[side*.97,1.98,.02],[side*.65,2.3,.02],[side*.35,2.42,.025]],.105,silver,110);
    tube([[side*.45,.1,.08],[side*1.05,.4,.04],[side*1.62,.8,.07],[side*1.77,1.2,.1],[side*1.65,1.58,.11],[side*1.31,1.72,.11],[side*.92,1.89,.11],[side*.6,2.22,.11]],.026,edge,90);
    // Angular snout, swept horns and dorsal fins rather than flat handle cutouts.
    const head=mesh(new T.SphereGeometry(.16,10,8),edge,[side*.34,2.4,.04]); head.scale.set(1.4,.68,.78); head.rotation.z=side*.2;
    const jaw=mesh(new T.BoxGeometry(.22,.065,.15),silver,[side*.33,2.33,.04]); jaw.rotation.z=side*.17;
    tube([[side*.56,2.33,-.015],[side*.64,2.55,-.03],[side*.76,2.67,-.09]],.035,edge,24);
    for(let f=0; f<7; f++) {
      const t=f/7;
      const fin=mesh(new T.ConeGeometry(.09*(1-t*.3),.24,3),edge,[side*(1.73-t*.95),1.61+t*.66,-.05]);
      fin.rotation.z=-side*(.8-t*.2); fin.rotation.y=.4;
    }
    mesh(new T.SphereGeometry(.025,8,6),ice,[side*.35,2.44,.16]);
  }
  // A raised central crest, with real bevels and a small editable typographic badge.
  const crest = new T.Shape();
  crest.moveTo(0,-.42); crest.lineTo(-.4,.11); crest.lineTo(-.32,.62); crest.lineTo(-.14,.51); crest.lineTo(0,.8); crest.lineTo(.14,.51); crest.lineTo(.32,.62); crest.lineTo(.4,.11); crest.closePath();
  const crestGeometry=new T.ExtrudeGeometry(crest,{depth:.025,bevelEnabled:true,bevelThickness:.012,bevelSize:.015,bevelSegments:2,steps:1});
  const cp=crestGeometry.attributes.position;
  for(let i=0;i<cp.count;i++){
    const x=cp.getX(i)*.65, y=cp.getY(i)*.7+.78;
    let radius=1;
    for(let j=0;j<6;j++)if(y>=profile[j][1] && y<=profile[j+1][1]){
      const t=(y-profile[j][1])/(profile[j+1][1]-profile[j][1]);radius=profile[j][0]*(1-t)+profile[j+1][0]*t;break;
    }
    cp.setXYZ(i,x,y,Math.sqrt(Math.max(.1,radius*radius-x*x))+cp.getZ(i)+.024);
  }
  crestGeometry.computeVertexNormals();mesh(crestGeometry,edge);
  const badgeCanvas=document.createElement('canvas'); badgeCanvas.width=512;badgeCanvas.height=256;
  const bctx=badgeCanvas.getContext('2d'); bctx.fillStyle='#d2e5fa';bctx.font='900 132px Arial';bctx.textAlign='center';bctx.fillText('KPL',256,156);
  const badgeTexture=new T.CanvasTexture(badgeCanvas);badgeTexture.colorSpace=T.SRGBColorSpace;
  const badgeMat=new T.MeshBasicMaterial({map:badgeTexture,transparent:true,depthWrite:false});
  mesh(new T.PlaneGeometry(.36,.18),badgeMat,[0,1.03,1.075]);
  trophy.rotation.set(-.04,-.32,-.025);
  trophy.updateMatrixWorld(true);

  // Sample actual triangles so the particle silhouette is the same 3D object.
  const triangles=[], cumulative=[]; let area=0;
  const va=new T.Vector3(),vb=new T.Vector3(),vc=new T.Vector3(),cross=new T.Vector3();
  trophy.traverse(o=>{
    if(!o.isMesh || o.material===badgeMat)return;
    const p=o.geometry.attributes.position, ix=o.geometry.index;
    const count=ix?ix.count:p.count;
    for(let i=0;i<count;i+=3) {
      va.fromBufferAttribute(p,ix?ix.getX(i):i).applyMatrix4(o.matrix);
      vb.fromBufferAttribute(p,ix?ix.getX(i+1):i+1).applyMatrix4(o.matrix);
      vc.fromBufferAttribute(p,ix?ix.getX(i+2):i+2).applyMatrix4(o.matrix);
      const a=cross.subVectors(vb,va).cross(new T.Vector3().subVectors(vc,va)).length()*.5;
      if(a<1e-8)continue;
      area+=a; cumulative.push(area); triangles.push([...va.toArray(),...vb.toArray(),...vc.toArray()]);
    }
  });
  const count=matchMedia('(max-width:600px)').matches?5500:14000;
  const positions=new Float32Array(count*3), seeds=new Float32Array(count*3);
  for(let i=0;i<count;i++) {
    const v=Math.random()*area; let lo=0,hi=cumulative.length-1;
    while(lo<hi){const mid=(lo+hi)>>1;if(cumulative[mid]<v)lo=mid+1;else hi=mid;}
    const tr=triangles[lo]; const r=Math.sqrt(Math.random()), s=Math.random();
    for(let a=0;a<3;a++){positions[i*3+a]=(1-r)*tr[a]+r*(1-s)*tr[a+3]+r*s*tr[a+6];seeds[i*3+a]=Math.random();}
  }
  const pg=new T.BufferGeometry();pg.setAttribute('position',new T.BufferAttribute(positions,3));pg.setAttribute('aSeed',new T.BufferAttribute(seeds,3));
  const uniforms={uTime:{value:0},uScatter:{value:0},uPixelRatio:{value:renderer.getPixelRatio()},uOpacity:{value:.22}};
  const particleMat=new T.ShaderMaterial({transparent:true,depthWrite:false,blending:T.AdditiveBlending,uniforms,
    vertexShader:`attribute vec3 aSeed; uniform float uTime; uniform float uScatter; uniform float uPixelRatio; varying vec3 vColor; varying float vAlpha;
      void main(){
        vec3 p=position;
        float a=aSeed.z*12.56637+step(.5,aSeed.x)*3.14159+uTime*.24;
        vec3 cloud=vec3(cos(a)*(1.2+aSeed.y*.6), (aSeed.z-.5)*5.1, sin(a)*(1.2+aSeed.y*.6));
        p=mix(p,cloud,uScatter);
        p+=sin(uTime*.7+aSeed*18.)*.014;
        vec4 mv=modelViewMatrix*vec4(p,1.);
        gl_Position=projectionMatrix*mv;
        gl_PointSize=min(7.,(16.+aSeed.x*24.)*uPixelRatio/-mv.z);
        vColor=mix(vec3(.3,.64,1.),vec3(1.,.23,.36),smoothstep(-1.2,1.2,p.x));
        if(aSeed.z>.7)vColor=vec3(.8,.9,1.);
        vAlpha=.38+aSeed.y*.62;
      }`,
    fragmentShader:`uniform float uOpacity; varying vec3 vColor; varying float vAlpha;
      void main(){float d=length(gl_PointCoord-.5);if(d>.5)discard;float a=smoothstep(.5,.06,d);gl_FragColor=vec4(vColor,a*vAlpha*uOpacity);}`
  });
  const particles=new T.Points(pg,particleMat);trophy.add(particles);
  // Elliptical resource orbit supplies an extra depth reference beneath the trophy.
  const orbit=new T.Group();scene.add(orbit);
  for(const [radius,color] of [[2.5,0x3268a1],[2.7,0x743345]]) {
    const points=[];for(let i=0;i<=160;i++){const a=i/160*Math.PI*2;points.push(new T.Vector3(Math.cos(a)*radius,-2.17,Math.sin(a)*radius));}
    orbit.add(new T.Line(new T.BufferGeometry().setFromPoints(points),new T.LineBasicMaterial({color,transparent:true,opacity:.35})));
  }

  let auto=!reduced.matches, scattered=false, visible=true, frame=0, last=0, time=0;
  let yaw=-.32,pitch=-.04,aimYaw=yaw,aimPitch=pitch,scatter=0,targetScatter=0;
  let dragging=false,lastX=0,lastY=0,moved=false;
  const materials=[silver,edge,dark,ice,badgeMat];
  // Set blending before the first shader compilation (otherwise OPAQUE can survive a later toggle).
  for(const material of materials)material.transparent=true;
  function labels(){
    toggle.hidden=false;burst.hidden=false;reset.hidden=false;
    toggle.textContent=auto?'暂停自转 Ⅱ':'开启自转 ▶'; toggle.setAttribute('aria-pressed',String(auto));
    burst.textContent=scattered?'聚合成形 ↗':'粒子解构 ✧';burst.setAttribute('aria-pressed',String(scattered));
    hint.textContent='移动鼠标看侧面 · 拖动旋转';
  }
  function render(now=0){
    frame=0;if(!visible || document.hidden)return;
    const dt=last?Math.min((now-last)/1000,.05):1/60;last=now;
    if(auto)time+=dt;
    const ease=reduced.matches?1:1-Math.exp(-dt*7);
    yaw+=(aimYaw-yaw)*ease;pitch+=(aimPitch-pitch)*ease;
    const morphEase=reduced.matches?1:1-Math.exp(-dt*3.4);
    scatter+=(targetScatter-scatter)*morphEase;
    trophy.rotation.y=yaw+(auto?Math.sin(time*.33)*.24:0);
    trophy.rotation.x=pitch;
    trophy.position.y=auto?Math.sin(time*.7)*.035:0;
    uniforms.uTime.value=time;uniforms.uScatter.value=scatter;
    uniforms.uOpacity.value=.18+scatter*.82;
    for(const material of materials){material.transparent=true;material.opacity=Math.max(0,1-scatter*1.2);material.depthWrite=scatter<.65;}
    renderer.render(scene,camera);
    hero.dataset.rotation=trophy.rotation.y.toFixed(3);hero.dataset.scatter=scatter.toFixed(3);
    hero.dataset.motion=auto?'running':'paused';
    hero.dataset.triangles=String(renderer.info.render.triangles);
    if(auto || Math.abs(aimYaw-yaw)>.0005 || Math.abs(aimPitch-pitch)>.0005 || Math.abs(targetScatter-scatter)>.001)request();
  }
  function request(){if(!frame && visible && !document.hidden)frame=requestAnimationFrame(render);}
  function resize(){
    const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;
    renderer.setSize(w,h,false); camera.aspect=w/h;
    camera.position.z=camera.aspect<.78?11.5:9.6;
    camera.updateProjectionMatrix();request();
  }
  function resetView(){aimYaw=-.32;aimPitch=-.04;time=0;request();}
  hero.addEventListener('pointermove',e=>{
    if(dragging)return;
    if(e.pointerType==='touch' || e.target.closest('a,button,input'))return;
    const box=canvas.getBoundingClientRect();
    const nx=Math.max(-1,Math.min(1,(e.clientX-box.left)/box.width*2-1));
    const ny=Math.max(-1,Math.min(1,(e.clientY-box.top)/box.height*2-1));
    aimYaw=-.32+nx*.82;aimPitch=-.04+ny*.2;request();
  },{passive:true});
  canvas.addEventListener('pointerdown',e=>{dragging=true;moved=false;lastX=e.clientX;lastY=e.clientY;canvas.setPointerCapture(e.pointerId);canvas.classList.add('dragging');});
  canvas.addEventListener('pointermove',e=>{
    if(!dragging)return;
    aimYaw+=(e.clientX-lastX)*.012;aimPitch=Math.max(-.5,Math.min(.5,aimPitch+(e.clientY-lastY)*.006));
    moved=moved || Math.abs(e.clientX-lastX)>1;lastX=e.clientX;lastY=e.clientY;request();
  },{passive:true});
  function endDrag(){dragging=false;canvas.classList.remove('dragging');}
  canvas.addEventListener('pointerup',endDrag);canvas.addEventListener('pointercancel',endDrag);
  canvas.addEventListener('lostpointercapture',endDrag);
  canvas.addEventListener('keydown',e=>{
    if(e.key==='ArrowLeft')aimYaw-=.25;else if(e.key==='ArrowRight')aimYaw+=.25;
    else if(e.key==='ArrowUp')aimPitch=Math.max(-.5,aimPitch-.1);else if(e.key==='ArrowDown')aimPitch=Math.min(.5,aimPitch+.1);
    else if(e.key.toLowerCase()==='r')resetView();else return;
    e.preventDefault();request();
  });
  toggle.addEventListener('click',()=>{auto=!auto;last=0;labels();request();});
  burst.addEventListener('click',()=>{scattered=!scattered;targetScatter=scattered?1:0;labels();request();});
  reset.addEventListener('click',resetView);
  reduced.addEventListener('change',()=>{auto=!reduced.matches;labels();request();});
  document.addEventListener('visibilitychange',()=>{last=0;if(document.hidden){cancelAnimationFrame(frame);frame=0;}else request();});
  new ResizeObserver(resize).observe(canvas);
  new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;last=0;if(visible)request();else{cancelAnimationFrame(frame);frame=0;hero.dataset.motion='paused';}},{threshold:0}).observe(hero);
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();cancelAnimationFrame(frame);frame=0;showPoster();});
  canvas.addEventListener('webglcontextrestored',()=>{hero.dataset.renderer='webgl';hero.classList.add('arena-3d-ready');labels();resize();request();});
  // Diagnostics expose rendered geometry counts without making the Three scene global.
  hero.dataset.renderer='webgl';hero.dataset.particles=String(count);hero.dataset.meshes=String(trophy.children.filter(o=>o.isMesh).length);
  labels();resize();renderer.render(scene,camera);hero.classList.add('arena-3d-ready');request();
}
