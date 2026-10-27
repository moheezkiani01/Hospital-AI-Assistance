/* Hospital AI patient UI interactions. All messages/actions continue through app.js. */
(() => {
  'use strict';
  const paths={
    'heart-pulse':'<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/><path d="M3.5 12h4l2-3 2.4 6 2-3H21"/>',
    'plus':'<path d="M12 5v14M5 12h14"/>','arrow-up-right':'<path d="M7 17 17 7M8 7h9v9"/>','arrow-right':'<path d="M5 12h14m-6-6 6 6-6 6"/>','arrow-up':'<path d="M12 19V5m-7 7 7-7 7 7"/>',
    'calendar-plus':'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4m8-4v4M3 10h18m-9 3v6m-3-3h6"/>',
    'calendar-days':'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4m8-4v4M3 10h18M8 14h.01M12 14h.01M16 14h.01"/>',
    'clipboard-list':'<rect x="5" y="4" width="14" height="18" rx="2"/><rect x="9" y="2" width="6" height="4" rx="1"/><path d="M9 12h6m-6 4h6"/>',
    'calendar-clock':'<path d="M16 3v4M8 3v4M3 10h18M20 15a5 5 0 1 1-5-5"/><path d="M3 8V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v3M20 12v3l2 1"/>',
    'calendar-x':'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18m-11 4 5 5m0-5-5 5"/>',
    'headset':'<path d="M3 15v-3a9 9 0 0 1 18 0v3M3 13h4v6H5a2 2 0 0 1-2-2Zm18 0h-4v6h2a2 2 0 0 0 2-2ZM17 21h-5"/>',
    'chevron-right':'<path d="m9 18 6-6-6-6"/>','shield-alert':'<path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="M12 7v6m0 4h.01"/>',
    'shield-check':'<path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/>',
    'sparkles':'<path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3ZM19 17l.7 2.3L22 20l-2.3.7L19 23l-.7-2.3L16 20l2.3-.7L19 17Z"/>',
    'menu':'<path d="M4 6h16M4 12h16M4 18h16"/>','x':'<path d="M18 6 6 18M6 6l12 12"/>','layout-panel-right':'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
    'message-circle':'<path d="M21 11.5A8.5 8.5 0 0 1 8.5 19L3 21l2-5.5A8.5 8.5 0 1 1 21 11.5Z"/>',
    'clock':'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>','stethoscope':'<path d="M6 3v5a5 5 0 0 0 10 0V3M4 3h4m6 0h4M11 13v2a5 5 0 0 0 10 0v-1"/><circle cx="21" cy="12" r="2"/>',
    'info':'<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/>','calendar-heart':'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4m8-4v4M3 10h18m-12 4c1-1 2 0 3 1 1-1 2-2 3-1 1 2-3 4-3 4s-4-2-3-4Z"/>',
    'circle-check':'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>'
  };
  document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=`<svg aria-hidden="true" viewBox="0 0 24 24">${paths[el.dataset.icon]||paths.info}</svg>`);
  document.getElementById('conversation-date').textContent=new Intl.DateTimeFormat('en',{weekday:'short',month:'short',day:'numeric'}).format(new Date());
  const sidebar=document.getElementById('patient-sidebar');
  const sidebarOverlay=document.getElementById('patient-sidebar-overlay');
  const sideBtn=document.getElementById('patient-menu-toggle');
  const forms=document.getElementById('patient-tools-panel');
  const overlay=document.getElementById('mobile-tool-overlay');
  const panels=[...forms.querySelectorAll('.panel')];
  const toolButtons=[...document.querySelectorAll('.patient-tools button')];
  const isMobile=()=>window.matchMedia('(max-width: 900px)').matches;
  const closeSidebar=()=>{sidebar.classList.remove('open');sidebarOverlay.hidden=true;sideBtn.setAttribute('aria-expanded','false');};
  const closeTools=()=>{forms.classList.remove('open');overlay.hidden=true;};
  sideBtn.addEventListener('click',()=>{const next=!sidebar.classList.contains('open');sidebar.classList.toggle('open',next);sidebarOverlay.hidden=!next;sideBtn.setAttribute('aria-expanded',String(next));});
  sidebarOverlay.addEventListener('click',closeSidebar);
  overlay.addEventListener('click',closeTools);
  document.getElementById('close-form-panel').addEventListener('click',closeTools);
  document.addEventListener('keydown',ev=>{if(ev.key==='Escape'){closeSidebar();closeTools();}});
  function syncPanels(){
    const current=panels.find(p=>!p.classList.contains('hidden'));
    document.getElementById('tools-empty-state').classList.toggle('hidden',Boolean(current));
    toolButtons.forEach(b=>b.classList.toggle('active',current?.id===b.dataset.panel));
    if(current&&isMobile()){forms.classList.add('open');overlay.hidden=false;closeSidebar();}
  }
  panels.forEach(p=>new MutationObserver(syncPanels).observe(p,{attributes:true,attributeFilter:['class']}));
  toolButtons.forEach(btn=>btn.addEventListener('click',()=>{closeSidebar();if(isMobile()){forms.classList.add('open');overlay.hidden=false;}}));
  document.getElementById('patient-help-toggle').addEventListener('click',()=>{
    if(isMobile() && forms.classList.contains('open'))return closeTools();
    if(!panels.some(p=>!p.classList.contains('hidden'))) window.openAppointmentForm?.();
    if(isMobile()){forms.classList.add('open');overlay.hidden=false;}
    else forms.scrollIntoView({behavior:'smooth',block:'nearest'});
  });
  window.addEventListener('resize',()=>{if(!isMobile()){closeSidebar();closeTools();}});
  syncPanels();
  const chatBox=document.getElementById('chat-box');
  const emptyState=document.getElementById('chat-empty-state');
  const input=document.getElementById('message-input');
  const send=document.getElementById('chat-send-button');
  const typing=document.getElementById('assistant-typing');
  function syncChat(){
    emptyState.classList.toggle('is-hidden',chatBox.querySelector('.message')!==null);
    if(chatBox.children.length){chatBox.scrollTop=chatBox.scrollHeight;}
  }
  function syncLoading(){typing.hidden=!input.disabled;send.disabled=input.disabled; if(input.disabled){chatBox.scrollTop=chatBox.scrollHeight;}}
  new MutationObserver(syncChat).observe(chatBox,{childList:true});
  new MutationObserver(syncLoading).observe(input,{attributes:true,attributeFilter:['disabled']});
  syncChat();syncLoading();
  // Existing new-chat function handles session reset and clearing the conversation.
  // The observer above restores the welcome view automatically.
})();
