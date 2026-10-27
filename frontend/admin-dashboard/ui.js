/* Hospital AI admin UI enhancements. No API changes or hardcoded hospital data. */
(() => {
  'use strict';
  const paths = {
    'heart-pulse':'<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/><path d="M3.5 12h4l2-3 2.4 6 2-3H21"/>',
    'layout-dashboard':'<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
    'calendar-days':'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01"/>',
    'calendar-check':'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18m5 6 2 2 4-4"/>',
    'stethoscope':'<path d="M6 3v5a5 5 0 0 0 10 0V3M4 3h4m6 0h4M11 13v2a5 5 0 0 0 10 0v-1"/><circle cx="21" cy="12" r="2"/>',
    'users':'<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M16 3.1a4 4 0 0 1 0 7.8M23 21v-2a4 4 0 0 0-3-3.9"/><circle cx="8.5" cy="7" r="4"/>',
    'messages-square':'<path d="M21 11.5a7.5 7.5 0 0 1-7.5 7.5H7l-4 3v-8A7.5 7.5 0 0 1 10.5 6H14"/><path d="M13 3h8v8l-3-2h-5z"/>',
    'message-circle-heart':'<path d="M21 11.5A8.5 8.5 0 0 1 8.5 19L3 21l2-5.5A8.5 8.5 0 1 1 21 11.5Z"/><path d="M8 10c1-2 3 0 4 1 1-1 3-3 4-1 1 2-4 5-4 5s-5-3-4-5Z"/>',
    'help-circle':'<circle cx="12" cy="12" r="9"/><path d="M9.6 9a2.5 2.5 0 1 1 4.4 1.8c-.9 1-2 1.2-2 2.5M12 17h.01"/>',
    'book-open':'<path d="M12 7c-3-2-6-2-9-1v13c3-1 6-1 9 1 3-2 6-2 9-1V6c-3-1-6-1-9 1Zm0 0v13"/>',
    'files':'<path d="M7 3h9l4 4v13H7zM16 3v5h4M4 7H3v14h12"/>',
    'network':'<rect x="9" y="2" width="6" height="5" rx="1"/><rect x="2" y="17" width="6" height="5" rx="1"/><rect x="16" y="17" width="6" height="5" rx="1"/><path d="M12 7v5M5 17v-5h14v5"/>',
    'layers-3':'<path d="m12 2 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 17l9 5 9-5"/>',
    'flask-conical':'<path d="M9 2h6m-5 0v7l-7 11a1.4 1.4 0 0 0 1.2 2h15.6a1.4 1.4 0 0 0 1.2-2L14 9V2M7 16h10"/>',
    'shield-alert':'<path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="M12 7v6m0 4h.01"/>',
    'headset':'<path d="M3 15v-3a9 9 0 0 1 18 0v3M3 13h4v6H5a2 2 0 0 1-2-2Zm18 0h-4v6h2a2 2 0 0 0 2-2ZM17 21h-5"/>',
    'building-2':'<path d="M3 21V4h11v17M14 9h7v12M6 8h2m2 0h1M6 12h2m2 0h1M6 16h2m2 0h1M17 13h2m-2 4h2M2 21h20"/>',
    'chevrons-up-down':'<path d="m7 10 5-5 5 5m-10 4 5 5 5-5"/>',
    'shield-check':'<path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/>',
    'circle-check':'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    'menu':'<path d="M4 6h16M4 12h16M4 18h16"/>',
    'x':'<path d="M18 6 6 18M6 6l12 12"/>',
    'search':'<circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/>',
    'external-link':'<path d="M12 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7M14 3h7v7m-9 2 9-9"/>',
    'moon':'<path d="M20.5 15A8.5 8.5 0 0 1 9 3.5 8.6 8.6 0 1 0 20.5 15Z"/>',
    'sun':'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/>',
    'log-out':'<path d="M10 17l5-5-5-5m5 5H3M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6"/>',
    'user-round':'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    'arrow-right':'<path d="M5 12h14m-6-6 6 6-6 6"/>',
    'activity':'<path d="M2 12h4l3-7 4 14 3-7h6"/>'
  };
  const svg = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths['circle-check']}</svg>`;
  document.querySelectorAll('[data-icon]').forEach(node => {
    const markup = svg(node.dataset.icon);
    if (node.matches('.sidebar-menu a')) node.insertAdjacentHTML('afterbegin', markup);
    else node.innerHTML = markup;
  });
  const side = document.getElementById('admin-sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  const toggle = document.getElementById('sidebar-toggle');
  const close = () => {side.classList.remove('open'); overlay.hidden = true; toggle.setAttribute('aria-expanded','false');};
  toggle.addEventListener('click',() => {const open = !side.classList.contains('open'); side.classList.toggle('open',open); overlay.hidden=!open;toggle.setAttribute('aria-expanded',String(open));});
  document.getElementById('sidebar-close').addEventListener('click',close);
  overlay.addEventListener('click',close);
  document.addEventListener('keydown', event => {if(event.key==='Escape') close();});
  const links = [...document.querySelectorAll('.sidebar-menu a')];
  const label = document.getElementById('active-page-label');
  function makeActive(link){links.forEach(x => x.classList.toggle('active',x===link));label.textContent = link.textContent.trim();}
  links.forEach(link=>link.addEventListener('click',()=>{makeActive(link);close();}));
  // Section search searches navigation destinations only, never patient records.
  const sectionSearch = document.getElementById('section-search');
  sectionSearch.addEventListener('keydown',event=>{
    if(event.key!=='Enter')return;
    event.preventDefault();
    const q=sectionSearch.value.trim().toLowerCase();
    const target=links.find(link=>link.textContent.toLowerCase().includes(q));
    if(q && target){target.click();document.querySelector(target.getAttribute('href'))?.scrollIntoView({behavior:'smooth',block:'start'});sectionSearch.blur();}
  });
  const themeToggle=document.getElementById('admin-theme-toggle');
  try{if(localStorage.getItem('hospital_admin_theme')==='dark') document.body.classList.add('dark');}catch(e){}
  function syncTheme(){themeToggle.innerHTML=svg(document.body.classList.contains('dark')?'sun':'moon'); themeToggle.setAttribute('aria-label',document.body.classList.contains('dark')?'Switch to light mode':'Switch to dark mode');}
  syncTheme();
  themeToggle.addEventListener('click',()=>{document.body.classList.toggle('dark');try{localStorage.setItem('hospital_admin_theme',document.body.classList.contains('dark')?'dark':'light');}catch(e){}syncTheme();});
  for(const input of [document.getElementById('email'),document.getElementById('password')]) {
    input.addEventListener('keydown',ev=>{if(ev.key==='Enter'){ev.preventDefault();window.login?.();}});
  }
  const dateEl=document.getElementById('dashboard-current-date');
  dateEl.textContent=new Intl.DateTimeFormat('en',{weekday:'long',month:'short',day:'numeric',year:'numeric'}).format(new Date());
  const dataIds=['total-chat-messages','doctor-chat-count','appointment-chat-count','medical-safety-count','document-rag-count'];
  function updateRing(){
    const values=dataIds.map(id=>Math.max(0,Number(document.getElementById(id)?.textContent?.replaceAll(',','')||0)||0));
    const total=values[0]; const tagged=values.slice(1);const safe=tagged.reduce((a,b)=>a+b,0);
    const labels=safe>total&&safe>0?tagged.map(v=>v/safe*100):[...tagged.map(v=>total?v/total*100:0),total?Math.max(0,total-safe)/total*100:100];
    const colors=['#5865e8','#12a78f','#f59e65','#8c77db','#dfe5f1'];
    let from=0; const slices=labels.map((value,i)=>{const to=Math.min(100,from+value); const slice=`${colors[i]} ${from.toFixed(2)}% ${to.toFixed(2)}%`;from=to;return slice;});
    if(slices.length===4&&from<99.999)slices.push(`#dfe5f1 ${from.toFixed(2)}% 100%`);
    document.getElementById('activity-ring').style.background=`conic-gradient(${slices.join(',')})`;
    document.getElementById('activity-total').textContent=total.toLocaleString();
  }
  dataIds.forEach(id=>new MutationObserver(updateRing).observe(document.getElementById(id),{childList:true,characterData:true,subtree:true}));
  updateRing();
  // Keep scroll navigation in sync without modifying the existing data loaders.
  if('IntersectionObserver' in window){
    const observer=new IntersectionObserver(entries=>{
      if(window.scrollY<280)return;
      const visible=entries.filter(x=>x.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top)[0];
      if(!visible)return;
      const link=links.find(x=>x.getAttribute('href')==='#'+visible.target.id);
      if(link)makeActive(link);
    },{rootMargin:'-100px 0px -65% 0px'});
    links.forEach(x=>{const target=document.querySelector(x.getAttribute('href'));if(target)observer.observe(target);});
  }
})();
