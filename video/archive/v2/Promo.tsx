import React from 'react';
import {AbsoluteFill, Audio, Easing, Sequence, interpolate, spring, staticFile,
  useCurrentFrame, useVideoConfig} from 'remotion';
import production from '../production.json';

const C = {paper:'#f3f5f2', ink:'#183431', muted:'#72817c', green:'#169c75',
  light:'#d9f3e8', purple:'#8b6ba9', line:'#d8dfd9', white:'#ffffff'};
const font = '"PingFang SC", "Hiragino Sans GB", -apple-system, BlinkMacSystemFont, sans-serif';
const clamp = {extrapolateLeft:'clamp' as const, extrapolateRight:'clamp' as const};
const ease = Easing.bezier(.2,.8,.2,1);
const range = (f:number, a:number, b:number, x=0, y=1) => interpolate(f,[a,b],[x,y],{...clamp,easing:ease});

const Mic:React.FC<{size?:number;color?:string}> = ({size=70,color=C.green}) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
    <rect x="23" y="7" width="18" height="33" rx="9" fill={color}/>
    <path d="M15 29v3a17 17 0 0 0 34 0v-3M32 49v9M23 58h18" stroke={color} strokeWidth="4" strokeLinecap="round"/>
  </svg>
);

const Icon:React.FC<{name:string;size?:number;color?:string}> = ({name,size=30,color=C.ink}) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="none" stroke={color} strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round">
    {name==='pause' ? <><path d="M11 8v16M21 8v16" strokeWidth="5"/></> :
      name==='play' ? <path d="m11 7 14 9-14 9z" fill={color} stroke="none"/> :
      name==='stop' ? <rect x="8" y="8" width="16" height="16" rx="2" fill={color} stroke="none"/> :
      name==='check' ? <><circle cx="16" cy="16" r="12"/><path d="m10 16 4 4 8-9"/></> :
      name==='device' ? <><rect x="4" y="5" width="24" height="17" rx="3"/><path d="M16 22v5M10 27h12"/></> :
      name==='person' ? <><circle cx="16" cy="10" r="5"/><path d="M6 27c0-11 20-11 20 0"/></> :
      name==='menu' ? <><rect x="3" y="5" width="26" height="23" rx="3"/><path d="M3 11h26M8 8h1M13 8h1"/></> :
      name==='lock' ? <><rect x="7" y="14" width="18" height="14" rx="3"/><path d="M11 14V9a5 5 0 0 1 10 0v5M16 20v3"/></> :
      <><circle cx="16" cy="16" r="5"/><path d="M16 3v4M16 25v4M3 16h4M25 16h4M7 7l3 3M22 22l3 3M7 25l3-3M22 10l3-3"/></>}
  </svg>
);

const Reveal:React.FC<{children:React.ReactNode;at?:number;style?:React.CSSProperties}> = ({children,at=0,style}) => {
  const f=useCurrentFrame();
  const p=range(f,at,at+22);
  return <div style={{opacity:p,transform:`translateY(${(1-p)*35}px)`,...style}}>{children}</div>;
};

const Scene:React.FC<{children:React.ReactNode;duration:number}> = ({children,duration}) => {
  const f=useCurrentFrame();
  return <AbsoluteFill style={{opacity:Math.min(range(f,0,10),1-range(f,duration-10,duration)),background:C.paper}}>{children}</AbsoluteFill>;
};

const Eyebrow:React.FC<{children:React.ReactNode}> = ({children}) => (
  <div style={{color:C.green,fontSize:23,fontWeight:600,letterSpacing:3,marginBottom:26}}>{children}</div>
);
const Title:React.FC<{children:React.ReactNode;size?:number;style?:React.CSSProperties}> = ({children,size=88,style}) => (
  <div style={{fontSize:size,fontWeight:650,lineHeight:1.23,letterSpacing:-3,color:C.ink,...style}}>{children}</div>
);
const Pill:React.FC<{children:React.ReactNode;green?:boolean}> = ({children,green}) => (
  <div style={{border:`1px solid ${green?'#b8dfce':C.line}`,background:green?C.light:'rgba(255,255,255,.72)',
    color:green?C.green:C.muted,fontSize:23,padding:'13px 23px',borderRadius:50,whiteSpace:'nowrap'}}>{children}</div>
);

const Wave:React.FC<{x:number;y:number;width:number;height:number;color:string;count?:number;phase?:number;strength?:number}> =
({x,y,width,height,color,count=80,phase=0,strength=1}) => {
  const f=useCurrentFrame();
  return <svg style={{position:'absolute',left:x,top:y,overflow:'visible'}} width={width} height={height}>
    {Array.from({length:count},(_,i)=>{
      const env=.18+.82*Math.pow(Math.sin(i/(count-1)*Math.PI),.8);
      const amp=(.3+.7*Math.abs(Math.sin(i*.62+f*.085+phase)*Math.cos(i*.21-f*.035+phase)))*env;
      const h=strength<=.001?2:6+amp*(height-6)*strength;
      return <rect key={i} x={i*width/count} y={(height-h)/2} width={Math.max(3,width/count*.45)} height={h} rx={3} fill={color}/>;
    })}
  </svg>;
};

const Opening:React.FC = () => {
  const f=useCurrentFrame();
  const intrusion=range(f,105,145);
  return <Scene duration={300}>
    <div style={{position:'absolute',left:126,top:150}}>
      <Reveal><Eyebrow>开放办公 · 公共空间</Eyebrow><Title size={77}>同处一间办公室，<br/>说的却不止一件事。</Title></Reveal>
      <Reveal at={28} style={{marginTop:22,fontSize:28,color:C.muted}}>你在口述方案，身旁的讨论也被麦克风收进来。</Reveal>
    </div>
    {[
      {at:20,y:450,color:C.green,label:'你的口述',quote:'「请把方案发给客户。」',phase:0},
      {at:60,y:643,color:C.purple,label:'身旁的讨论',quote:'「下午三点开会。」',phase:2.6},
    ].map(source=><Reveal key={source.label} at={source.at} style={{position:'absolute',left:126,top:source.y}}>
      <div style={{position:'relative',width:775,height:166,borderRadius:24,border:'1px solid '+C.line,background:'#ffffffba'}}>
        <div style={{position:'absolute',left:29,top:25,fontSize:23,color:source.color,display:'flex',gap:11,alignItems:'center'}}>
          <span style={{width:9,height:9,borderRadius:10,background:source.color}}/>{source.label}
        </div>
        <div style={{position:'absolute',left:26,top:79,fontSize:33,color:C.ink,fontWeight:500}}>{source.quote}</div>
        <Wave x={474} y={46} width={267} height={79} color={source.color} count={40} phase={source.phase}/>
      </div>
    </Reveal>)}
    <Reveal at={75} style={{position:'absolute',left:928,top:550,width:145,textAlign:'center'}}>
      <Mic size={50} color={C.muted}/><div style={{marginTop:9,fontSize:21,color:C.muted}}>一同收音</div>
      <svg width="126" height="34" style={{marginTop:16}}><path d="M8 17h105m-9-8 9 8-9 8" stroke={C.muted} strokeWidth="2" fill="none"/></svg>
    </Reveal>
    <Reveal at={86} style={{position:'absolute',left:1099,top:450,width:695}}>
      <div style={{border:'1px solid '+C.line,borderRadius:24,background:'#ffffffc4',padding:'29px 34px',height:359,boxSizing:'border-box'}}>
        <div style={{fontSize:23,color:C.muted,marginBottom:33}}>语音输入中的一句话</div>
        <div style={{fontSize:37,fontWeight:500,lineHeight:1.7,color:C.green}}>请把方案</div>
        <div style={{fontSize:37,fontWeight:500,lineHeight:1.7,color:C.purple,opacity:intrusion,background:'#f0eaf4',borderRadius:10,padding:'0 14px',marginLeft:-14,width:310}}>下午三点开会</div>
        <div style={{fontSize:37,fontWeight:500,lineHeight:1.7,color:C.green}}>发给客户。</div>
      </div>
    </Reveal>
    <Reveal at={145} style={{position:'absolute',left:126,top:867,fontSize:30,color:C.ink,fontWeight:500}}>身旁的话，混进了你的句子。</Reveal>
    <div style={{position:'absolute',right:126,bottom:103,fontSize:20,color:C.muted}}>情境演绎 · 非实测转写结果</div>
  </Scene>;
};

const Brand:React.FC = () => {
  const f=useCurrentFrame(); const {fps}=useVideoConfig();
  const p=spring({frame:f-8,fps,config:{damping:18,stiffness:100}});
  return <Scene duration={180}>
    <div style={{position:'absolute',left:128,top:248,width:310,height:310,borderRadius:78,background:C.light,
      boxShadow:'0 30px 70px #1834310c',transform:`scale(${.8+.2*p}) rotate(${(1-p)*-9}deg)`,display:'flex',alignItems:'center',justifyContent:'center'}}>
      <Mic size={168}/>
    </div>
    <div style={{position:'absolute',left:525,top:249}}>
      <Reveal at={13}><div style={{fontSize:35,fontWeight:550,color:C.green,marginBottom:24}}>MicForYou</div></Reveal>
      <Reveal at={22}><Title size={94}>让自己的话，<br/>有自己的位置。</Title></Reveal>
      <Reveal at={45} style={{marginTop:33,fontSize:29,lineHeight:1.7,color:C.muted}}>用你的声音作参考，减少部分旁人的人声干扰。<br/>让热闹中的表达，多一点清楚。</Reveal>
    </div>
    <div style={{position:'absolute',left:128,bottom:165,display:'flex',alignItems:'center',gap:22}}>
      <div style={{width:11,height:11,borderRadius:20,background:C.green}}/>
      <div style={{fontSize:25,color:C.muted}}>Experimental Alpha</div>
    </div>
  </Scene>;
};

const Cursor:React.FC<{x:number;y:number;click?:boolean}> = ({x,y,click}) => (
  <div style={{position:'absolute',left:x,top:y,zIndex:20,filter:'drop-shadow(1px 3px 3px #0004)'}}>
    {click&&<div style={{position:'absolute',left:-22,top:-22,width:64,height:64,borderRadius:50,border:'3px solid #169c7555'}}/>}
    <svg width="46" height="52" viewBox="0 0 30 38"><path d="M3 2v28l7-7 6 12 5-3-6-11 10-1z" fill="#203933" stroke="white" strokeWidth="2"/></svg>
  </div>
);

const Menu:React.FC<{state:'ready'|'loading'|'running'|'paused';style?:React.CSSProperties}> = ({state,style}) => {
  const active=state==='running'; const paused=state==='paused';
  const labels={ready:['可以开始','隐私优先 · 故障时静音'],loading:['正在加载','首次加载可能需要一点时间'],running:['正在过滤','仅处理声音，不转写文字'],paused:['已暂停','BlackHole 当前无输出']};
  return <div style={{width:580,padding:28,background:'rgba(250,252,249,.98)',border:'1px solid #ccd7cd',borderRadius:20,
    boxShadow:'0 25px 70px #13392b21',...style}}>
    <div style={{display:'flex',alignItems:'center',gap:18}}>
      <div style={{width:66,height:66,borderRadius:40,background:active?C.light:'#e8eee6',display:'flex',alignItems:'center',justifyContent:'center'}}>
        {paused?<Icon name="pause" color={C.muted} size={29}/>:<Mic size={35} color={active?C.green:C.muted}/>}
      </div>
      <div style={{flex:1}}><div style={{fontSize:32,fontWeight:600,color:C.ink}}>{labels[state][0]}</div>
        <div style={{fontSize:20,color:C.muted,marginTop:6}}>{labels[state][1]}</div></div>
      <div style={{fontSize:18,color:C.muted,background:'#e8eee5',padding:'6px 13px',borderRadius:30}}>Alpha</div>
    </div>
    <div style={{marginTop:25,background:'#eaf0e7',padding:'17px 15px',borderRadius:11,display:'flex',alignItems:'center',gap:13,fontSize:20,color:C.muted}}>
      <Mic size={24} color={C.muted}/><span>External Microphone</span><span style={{margin:'0 7px'}}>›</span><span>BlackHole 2ch</span>
    </div>
    <div style={{marginTop:24,display:'flex',gap:14}}>
      <div style={{display:'flex',alignItems:'center',justifyContent:'center',gap:13,height:62,flex:1,color:'white',background:state==='loading'?'#a4b7aa':C.green,borderRadius:11,fontSize:26,fontWeight:500}}>
        <Icon name={active?'pause':'play'} color="white" size={24}/>{active?'暂停':paused?'继续过滤':state==='loading'?'正在加载':'开始过滤'}
      </div>
      {(active||paused||state==='loading')&&<div style={{display:'flex',alignItems:'center',justifyContent:'center',gap:9,width:146,background:'#e7eee3',borderRadius:11,fontSize:25}}><Icon name="stop" size={21}/>结束</div>}
    </div>
    {active||paused ? <div style={{fontSize:20,color:C.muted,display:'flex',gap:10,alignItems:'center',marginTop:23}}>
      <Icon name={paused?'pause':'check'} color={C.muted} size={23}/>{paused?'实体麦克风已释放；继续时会重建过滤状态':'豆包输入保持为 BlackHole 2ch'}</div>:null}
    <div style={{borderTop:'1px solid #d4decf',marginTop:26,paddingTop:20,display:'flex',fontSize:20,color:C.muted,gap:12,alignItems:'center'}}>
      <Icon name="settings" size={21} color={C.muted}/><span>设置</span><div style={{flex:1}}/><span>退出界面</span>
    </div>
  </div>;
};

type DemoState = 'ready'|'loading'|'running'|'paused';

const SoundPath:React.FC<{state:DemoState}> = ({state}) => {
  const f=useCurrentFrame();
  const running=state==='running'; const paused=state==='paused';
  const summaries={ready:'尚未开始 · 本链路无声音输出',loading:'正在准备 · 本链路无声音输出',
    running:'已开启 · 声音正在送往豆包',paused:'已暂停 · 本链路无声音输出'};
  const effects={ready:'准备好，再让声音向前。',loading:'稍等片刻，让声音找到自己的位置。',
    running:'你的口述继续向前，旁人的声音有所减弱。',paused:'办公室继续交谈，这条声音链路已经停下。'};
  const filter=range(f,production.demo.runAt,production.demo.runAt+25);
  return <div style={{position:'relative',width:934,height:442,borderRadius:26,border:'1px solid '+C.line,background:'#ffffffc7'}}>
    <div style={{position:'absolute',left:31,top:24,display:'flex',gap:12,alignItems:'center',fontSize:28,fontWeight:600,color:running?C.green:C.ink}}>
      <Icon name={running?'check':paused?'pause':'device'} color={running?C.green:C.muted} size={29}/>{summaries[state]}
    </div>
    <div style={{position:'absolute',left:33,top:91,fontSize:20,color:C.muted}}>办公室里的声音</div>
    <div style={{position:'absolute',left:538,top:91,fontSize:20,color:C.muted}}>送往豆包的声音</div>
    {['你的口述','身旁讨论'].map((name,i)=><React.Fragment key={name}>
      <div style={{position:'absolute',left:33,top:141+i*105,fontSize:22,color:i?C.purple:C.green}}>{name}</div>
      <Wave x={33} y={170+i*105} width={236} height={51} color={i?C.purple:C.green} count={35} phase={i*2.6}/>
      <Wave x={538} y={170+i*105} width={350} height={51} color={running?(i?C.purple:C.green):'#c1cbc4'} count={51}
        phase={i*2.6} strength={running?(i?1-filter*.58:1):0}/>
    </React.Fragment>)}
    <div style={{position:'absolute',left:348,top:174,width:117,height:117,borderRadius:30,background:running?C.light:'#edf0eb',
      display:'flex',alignItems:'center',justifyContent:'center'}}>{paused?<Icon name="pause" size={49} color={C.muted}/>:<Mic size={57} color={running?C.green:C.muted}/>}</div>
    <div style={{position:'absolute',left:344,top:304,width:125,textAlign:'center',fontSize:21,color:C.muted}}>MicForYou</div>
    {[{x:275,width:68},{x:468,width:61}].map((a,i)=><svg key={i} style={{position:'absolute',left:a.x,top:213}} width={a.width} height={32}>
      <path d={`M4 16h${a.width-15}m-7-6 7 6-7 6`} stroke={running?C.green:'#b7c4b9'} strokeWidth="2" strokeDasharray={running?undefined:'4 5'} fill="none"/>
      {running&&<circle cx={7+(f*1.2%(a.width-21))} cy={16} r={4} fill={C.green}/>}
    </svg>)}
    {!running&&<div style={{position:'absolute',left:568,top:233,padding:'8px 20px',fontSize:25,color:C.muted,background:'#f3f5f2',borderRadius:12}}>暂无声音输出</div>}
    <div style={{position:'absolute',left:33,bottom:25,fontSize:23,color:C.ink}}>{effects[state]}</div>
  </div>;
};

const Demo:React.FC = () => {
  const f=useCurrentFrame();
  const {loadAt,runAt,pauseAt}=production.demo;
  const state:DemoState=f<loadAt?'ready':f<runAt?'loading':f<pauseAt?'running':'paused';
  const paused=state==='paused';
  const cx=f<loadAt?range(f,42,81,811,430):f<320?range(f,155,180,430,811):
    f<pauseAt?range(f,320,350,811,358):range(f,395,420,358,811);
  const cy=f<loadAt?range(f,42,81,855,637):f<320?range(f,155,180,637,710):
    f<pauseAt?range(f,320,350,710,637):range(f,395,420,637,710);
  const click=(f>=88&&f<=96)||(f>=357&&f<=365);
  return <Scene duration={540}>
    <div style={{position:'absolute',left:126,top:142}}>
      <Reveal><Eyebrow>一句话的开始与停顿</Eyebrow><Title size={74}>{paused?<>停下来，<br/>也留一段安静。</>:<>一句话的开始，<br/>只需轻轻一点。</>}</Title></Reveal>
    </div>
    <div style={{position:'absolute',left:1130,top:220,display:'flex',gap:14}}>
      <Pill green={state==='ready'||state==='loading'}>01 准备</Pill><Pill green={state==='running'}>02 开启</Pill><Pill green={paused}>03 暂停</Pill>
    </div>
    <div style={{position:'absolute',left:126,top:400,width:667,height:463,borderRadius:25,border:'1px solid #ced8cb',background:'linear-gradient(135deg,#c8e0d2,#e6edda)',overflow:'hidden'}}>
      <div style={{height:48,background:'#ffffff72',display:'flex',alignItems:'center',padding:'0 24px',fontSize:21,color:C.ink}}>
        <span style={{fontWeight:600}}>MicForYou · 菜单栏</span><div style={{flex:1}}/><Mic size={24}/>
      </div>
    </div>
    <Menu state={state} style={{position:'absolute',left:150,top:469,transform:'scale(.88)',transformOrigin:'top left'}}/>
    <div style={{position:'absolute',left:860,top:400}}><SoundPath state={state}/></div>
    <Cursor x={cx} y={cy+36} click={click}/>
    <Reveal at={135} style={{position:'absolute',left:126,top:922,fontSize:28,color:C.ink,fontWeight:500}}>
      {paused?'暂停后，麦克风被释放，豆包不再收到这条链路的声音。':'按钮亮起，声音向前；旁人的交谈，少占一点位置。'}
    </Reveal>
    <div style={{position:'absolute',right:126,bottom:90,fontSize:19,color:C.muted}}>界面与声音效果示意 · 非实测对比 · 加载时间已压缩</div>
  </Scene>;
};

const Flow:React.FC = () => {
  const f=useCurrentFrame();
  const positions=[126,551,976,1401];
  const names=['你的麦克风','MicForYou','声音通道','豆包输入法'];
  const subs=['收下你要说的话','在本机处理声音','BlackHole 2ch','把声音变成文字'];
  const nodeIcons=['mic','person','device','menu'];
  return <Scene duration={210}>
    <div style={{position:'absolute',left:126,top:134}}>
      <Reveal><Eyebrow>熟悉的输入方式</Eyebrow><Title size={80}>从你的声音，<br/>到你熟悉的文字。</Title></Reveal>
    </div>
    {names.map((name,i)=><Reveal at={18+i*13} key={name} style={{position:'absolute',left:positions[i],top:434,width:350}}>
      <div style={{height:228,borderRadius:27,border:`1px solid ${i===1?'#a9d9c4':C.line}`,background:i===1?C.light:'#ffffffa8',
        display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',boxShadow:i===1?'0 18px 38px #169c750d':undefined}}>
        {i===0?<Mic size={62}/>:<Icon name={nodeIcons[i]} size={62} color={i===1?C.green:C.ink}/>}
        <div style={{fontSize:31,fontWeight:600,marginTop:23,color:C.ink}}>{name}</div>
      </div><div style={{fontSize:23,textAlign:'center',color:C.muted,marginTop:22}}>{subs[i]}</div>
    </Reveal>)}
    {positions.slice(0,3).map((x,i)=>{
      const p=range(f,45+i*15,72+i*15);
      return <svg key={x} style={{position:'absolute',left:x+350,top:537,opacity:p}} width={75} height={24}>
        <path d="M10 12h52m-8-6 8 6-8 6" stroke={C.green} strokeWidth={2} fill="none"/>
        <circle cx={10+((f*1.3+i*17)%48)} cy={12} r={4} fill={C.green}/>
      </svg>;
    })}
    <Reveal at={65} style={{position:'absolute',left:126,top:814,fontSize:30,color:C.ink}}>声音在 Mac 本机处理。习惯的豆包输入，照常继续。</Reveal>
    <div style={{position:'absolute',left:126,bottom:110,fontSize:21,color:C.muted}}>本机处理仅指 MicForYou 的声音前处理；豆包的数据处理遵循其自身规则。</div>
  </Scene>;
};

const Features:React.FC = () => {
  const cards=[{icon:'person',n:'01',title:'人声交错，少些干扰',body:'以你的注册声音作参考，\n减少部分旁人的声音。'},
    {icon:'device',n:'02',title:'照常口述，照常输入',body:'继续使用豆包输入法，\n保留熟悉的工作习惯。'},
    {icon:'menu',n:'03',title:'开始与停顿，由你掌握',body:'在菜单栏开启、暂停；\n暂停后释放麦克风。'}];
  return <Scene duration={210}>
    <div style={{position:'absolute',left:126,top:135}}><Reveal><Eyebrow>协作有声，表达有度</Eyebrow><Title size={73}>协作的热闹，<br/>不必都写进你的句子。</Title></Reveal></div>
    <div style={{position:'absolute',left:126,top:433,display:'flex',gap:30}}>
      {cards.map((card,i)=><Reveal key={card.n} at={15+i*17}>
        <div style={{width:535,height:382,background:i===0?C.light:'#ffffffa6',border:'1px solid '+C.line,borderRadius:30,padding:41,boxSizing:'border-box'}}>
          <div style={{display:'flex',alignItems:'center',justifyContent:'space-between'}}><Icon name={card.icon} size={53} color={C.green}/><span style={{fontSize:25,color:'#9cac9e'}}>{card.n}</span></div>
          <div style={{fontSize:32,fontWeight:600,color:C.ink,marginTop:43,whiteSpace:'nowrap'}}>{card.title}</div>
          <div style={{fontSize:27,lineHeight:1.7,color:C.muted,marginTop:18,whiteSpace:'pre-line'}}>{card.body}</div>
        </div>
      </Reveal>)}
    </div>
    <Reveal at={75} style={{position:'absolute',left:126,bottom:131,fontSize:24,color:C.muted}}>默认故障时静音；设备断开，也不会悄悄换一支麦克风。</Reveal>
  </Scene>;
};

const SharedOffice:React.FC = () => (
  <svg width="660" height="450" viewBox="0 0 660 450" fill="none" aria-label="开放工位中，一人正在口述，周围同事讨论和开会">
    <rect x="12" y="24" width="636" height="410" rx="47" fill="#e2eee5"/>
    <path d="M46 363h564M80 75h495M91 77v76m150-76v76m150-76v76m150-76v76" stroke="#c3d6c7" strokeWidth="2"/>
    <rect x="51" y="108" width="156" height="52" rx="17" fill="#f2ecf6"/><text x="129" y="141" fill={C.purple} fontSize="21" textAnchor="middle" fontFamily={font}>项目讨论</text>
    <rect x="443" y="108" width="160" height="52" rx="17" fill="#f2ecf6"/><text x="523" y="141" fill={C.purple} fontSize="21" textAnchor="middle" fontFamily={font}>线上会议</text>
    <circle cx="98" cy="204" r="24" fill="#ab96bb"/><circle cx="192" cy="204" r="24" fill="#b5a1c1"/>
    <path d="M70 270v-20c0-36 56-36 56 0v20M164 270v-20c0-36 56-36 56 0v20" fill="#cfbfd9"/>
    <circle cx="536" cy="204" r="24" fill="#ab96bb"/><path d="M508 270v-20c0-36 56-36 56 0v20" fill="#cfbfd9"/>
    <path d="M57 273h175m250 0h115M75 273v66m140-66v66m284-66v66m84-66v66" stroke="#a9bfaf" strokeWidth="4" strokeLinecap="round"/>
    <rect x="456" y="229" width="45" height="31" rx="5" fill="#e7dfed" stroke="#ad95bc" strokeWidth="2"/>
    <circle cx="333" cy="246" r="31" fill={C.green}/><path d="M292 334v-42c0-45 82-45 82 0v42" fill="#90c9b0"/>
    <rect x="286" y="182" width="108" height="45" rx="17" fill={C.light}/><text x="340" y="211" fill={C.green} fontSize="20" textAnchor="middle" fontFamily={font}>口述方案</text>
    <path d="M267 329h133m-123 0v53m113-53v53" stroke="#719e85" strokeWidth="5" strokeLinecap="round"/>
    <rect x="309" y="287" width="63" height="39" rx="5" fill="#d9f3e8" stroke={C.green} strokeWidth="2"/>
    <path d="M315 329h65" stroke={C.green} strokeWidth="4" strokeLinecap="round"/>
    <path d="M244 199c-30-10-58-12-91-8M424 199c30-10 54-12 84-8" stroke={C.purple} strokeWidth="2" strokeDasharray="4 8"/>
    <text x="332" y="413" fill="#6c8775" fontSize="21" textAnchor="middle" fontFamily={font}>一间办公室，几种不同的表达。</text>
  </svg>
);

const Ending:React.FC = () => (
  <Scene duration={210}>
    <div style={{position:'absolute',left:126,top:177,display:'flex',alignItems:'center',gap:23}}>
      <div style={{width:89,height:89,borderRadius:24,background:C.light,display:'flex',alignItems:'center',justifyContent:'center'}}><Mic size={53}/></div>
      <Reveal><div style={{fontSize:43,fontWeight:650,color:C.ink,letterSpacing:-1}}>MicForYou</div></Reveal>
    </div>
    <Reveal at={12} style={{position:'absolute',left:126,top:324}}><Title size={108}>空间共享，<br/><span style={{color:C.green}}>表达从容。</span></Title></Reveal>
    <Reveal at={30} style={{position:'absolute',left:126,top:626,fontSize:28,color:C.muted}}>开放工位里，一句自己的话，也值得被听清。</Reveal>
    <Reveal at={45} style={{position:'absolute',left:126,top:702,display:'flex',gap:13}}><Pill green>少些人声干扰</Pill><Pill>豆包输入照旧</Pill><Pill>开启、暂停由你</Pill></Reveal>
    <Reveal at={20} style={{position:'absolute',left:1130,top:282}}><SharedOffice/></Reveal>
    <Reveal at={15} style={{position:'absolute',left:126,top:851,width:1670,borderTop:'1px solid '+C.line,paddingTop:27,fontSize:23,lineHeight:1.65,color:C.muted}}>
      Experimental Alpha：可减少部分他人声，不能保证完全隔离；本人不说话时仍可能放行他人声。<br/>
      情境、界面与波形均为动画示意。MicForYou 在本机处理声音，豆包负责语音识别。
    </Reveal>
  </Scene>
);

export const Promo:React.FC = () => {
  const f=useCurrentFrame();
  const components:Record<string,React.FC>={opening:Opening,brand:Brand,demo:Demo,flow:Flow,features:Features,ending:Ending};
  const scenes=production.scenes.map(scene=>({start:scene.from,duration:scene.duration,component:components[scene.id]}));
  return <AbsoluteFill style={{background:C.paper,fontFamily:font,color:C.ink}}>
    <Audio src={staticFile('soundtrack.wav')}/>
    {scenes.map(({start,duration,component:Component})=><Sequence key={start} from={start} durationInFrames={duration}><Component/></Sequence>)}
    <div style={{position:'absolute',left:126,top:55,right:126,display:'flex',justifyContent:'space-between',alignItems:'center',fontSize:20,color:C.muted}}>
      <span style={{fontWeight:650,letterSpacing:-.4}}>MicForYou</span><span style={{fontSize:17,letterSpacing:1.2}}>EXPERIMENTAL ALPHA</span>
    </div>
    <div style={{position:'absolute',left:126,bottom:42,right:126,display:'flex',alignItems:'center',gap:14}}>
      {scenes.map(({start,duration},i)=><div key={i} style={{height:3,flex:duration,background:'#dce4db',borderRadius:4,overflow:'hidden'}}><div style={{height:'100%',width:`${range(f,start,start+duration)*100}%`,background:C.green}}/></div>)}
      <span style={{fontSize:16,color:C.muted,marginLeft:12,width:80,textAlign:'right',whiteSpace:'nowrap'}}>0{Math.min(6,scenes.findIndex(s=>f<s.start+s.duration)+1)} / 06</span>
    </div>
  </AbsoluteFill>;
};
