import './style.css';

const categories = [
  {id:'all', label:'Tất cả', icon:'✦'},
  {id:'air-m1', label:'Air M1', icon:'💻'},
  {id:'air-m2', label:'Air M2', icon:'💻'},
  {id:'air-m3', label:'Air M3', icon:'💻'},
  {id:'air-m4', label:'Air M4', icon:'💻'},
  {id:'pro-m1', label:'Pro M1', icon:'💻'},
  {id:'pro-m2', label:'Pro M2', icon:'💻'},
  {id:'pro-m3', label:'Pro M3', icon:'💻'},
  {id:'pro-m4', label:'Pro M4', icon:'💻'},
];
const listings = [
  {id:1,category:'air-m2',title:'MacBook Air M2 13” 16GB / 512GB · 98%',price:15000000,city:'TP. Hồ Chí Minh',time:'12 phút trước',seller:'Cá nhân',tone:'silver',badge:'Máy sạch',image:'https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=900&q=80'},
  {id:2,category:'pro-m1',title:'MacBook Pro 14” M1 Pro 16GB / 512GB',price:18500000,city:'Hà Nội',time:'28 phút trước',seller:'Cá nhân',tone:'space',badge:'Pin 92%',image:'https://images.unsplash.com/photo-1611186871348-b1ce696e52c9?w=900&q=80'},
  {id:3,category:'air-m4',title:'MacBook Air M4 16/512 · còn bảo hành',price:24900000,city:'Đà Nẵng',time:'45 phút trước',seller:'Cá nhân',tone:'silver',badge:'Fullbox',image:'https://images.unsplash.com/photo-1541807084-5c52b6b3adef?w=900&q=80'},
  {id:4,category:'air-m1',title:'MacBook Air M1 8GB / 256GB · ít dùng',price:9200000,city:'TP. Hồ Chí Minh',time:'1 giờ trước',seller:'Cá nhân',tone:'silver',badge:'Giá tốt',image:'https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=900&q=80'},
  {id:5,category:'pro-m3',title:'MacBook Pro M3 Pro 18GB / 512GB',price:30900000,city:'Hà Nội',time:'2 giờ trước',seller:'Cá nhân',tone:'space',badge:'Pin 97%',image:'https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=900&q=80'},
  {id:6,category:'air-m3',title:'MacBook Air M3 13” 16GB / 256GB',price:18100000,city:'Bình Dương',time:'3 giờ trước',seller:'Cá nhân',tone:'silver',badge:'Máy đẹp',image:'https://images.unsplash.com/photo-1611186871348-b1ce696e52c9?w=900&q=80'},
  {id:7,category:'pro-m2',title:'MacBook Pro M2 Pro 14” 16GB / 512GB',price:23600000,city:'TP. Hồ Chí Minh',time:'4 giờ trước',seller:'Cá nhân',tone:'space',badge:'Fullbox',image:'https://images.unsplash.com/photo-1541807084-5c52b6b3adef?w=900&q=80'},
  {id:8,category:'pro-m4',title:'MacBook Pro M4 14” 16GB / 512GB',price:36500000,city:'Hà Nội',time:'5 giờ trước',seller:'Cá nhân',tone:'silver',badge:'Còn BH',image:'https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=900&q=80'},
];
const icons = {
  menu:'<path d="M4 7h16M4 12h16M4 17h16"/>',
  heart:'<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
  bell:'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  search:'<circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/>',
  home:'<path d="m3 10 9-7 9 7v11H3z"/><path d="M9 21v-7h6v7"/>',
  tag:'<path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z"/><circle cx="8" cy="8" r="1"/>',
  message:'<path d="M21 11a8 8 0 0 1-8 8H5l-3 3v-11a9 9 0 1 1 19 0Z"/>',
  user:'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  plus:'<path d="M12 4v16M4 12h16"/>',
  pin:'<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2"/>'
};
const svg = (name,fill=false)=>`<svg width="23" height="23" viewBox="0 0 24 24" fill="${fill?'currentColor':'none'}" stroke="currentColor" stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]}</svg>`;
const state={category:'all',query:'',sort:'new',favorites:new Set(JSON.parse(localStorage.getItem('macket-favorites')||'[]')),tab:'home'};
const money=n=>new Intl.NumberFormat('vi-VN').format(n)+'đ';
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const app=document.querySelector('#app');
function filtered(){let items=listings.filter(p=>(state.category==='all'||p.category===state.category) && (!state.query || (p.title+' '+p.city).toLowerCase().includes(state.query.toLowerCase())));if(state.tab==='favorites')items=items.filter(p=>state.favorites.has(p.id));if(state.sort==='price')items.sort((a,b)=>a.price-b.price);return items;}
function cards(){const items=filtered();return items.length?items.map(p=>`<article class="listing" tabindex="0" aria-label="${esc(p.title)}"><div class="listing-photo"><img src="${p.image}" alt="Ảnh minh họa MacBook" loading="lazy"/><span class="photo-badge">${p.badge}</span><button class="favorite ${state.favorites.has(p.id)?'saved':''}" data-favorite="${p.id}" aria-label="${state.favorites.has(p.id)?'Bỏ lưu':'Lưu tin'}">${svg('heart',state.favorites.has(p.id))}</button></div><div class="listing-body"><div class="listing-title">${esc(p.title)}</div><div class="price">${money(p.price)}</div><div class="meta"><span>${svg('pin')} ${esc(p.city)}</span><span>${p.time}</span></div></div></article>`).join(''):'<div class="empty">Chưa có tin phù hợp. Thử chọn dòng MacBook khác nhé.</div>';}
function render(){app.innerHTML=`<div class="shell"><header class="hero"><div class="topbar"><button class="icon-btn" aria-label="Menu">${svg('menu')}</button><div class="logo">macket<span>.</span></div><div class="top-actions"><button class="icon-btn" data-tab="favorites" aria-label="Đã lưu">${svg('heart')}</button><button class="icon-btn" aria-label="Thông báo">${svg('bell')}</button></div></div><div class="headline"><div class="eyebrow">MACBOOK MARKETPLACE</div><h1>MacBook cũ,<br/>chọn đúng máy.</h1><p>Tin mới mỗi ngày · Ưu tiên người bán cá nhân</p></div><div class="search-wrap"><div class="search-field">${svg('search')}<input id="search" type="search" placeholder="Tìm MacBook, RAM, đời máy..." value="${esc(state.query)}" aria-label="Tìm sản phẩm"/><button id="search-action" aria-label="Tìm kiếm">${svg('search')}</button></div></div></header><main><section class="categories-section"><div class="section-title"><h2>Chọn dòng MacBook</h2><span>Khám phá theo chip</span></div><div class="category-list">${categories.map(c=>`<button class="category ${state.category===c.id?'active':''}" data-category="${c.id}"><span class="category-art">${c.icon}</span><span>${c.label}</span></button>`).join('')}</div></section><section class="feed"><div class="feed-head"><div><div class="feed-kicker">GỢI Ý CHO BẠN</div><h2>${state.tab==='favorites'?'Tin đã lưu':'MacBook đang được rao bán'}</h2></div><span class="count">${filtered().length} tin</span></div><div class="filter-row"><button class="chip ${state.sort==='new'?'selected':''}" data-sort="new">Mới nhất</button><button class="chip ${state.sort==='price'?'selected':''}" data-sort="price">Giá thấp trước</button><span class="demo-pill">Dữ liệu minh họa</span></div><div class="listing-grid">${cards()}</div></section></main><nav class="bottom-nav"><button class="nav-btn ${state.tab==='home'?'active':''}" data-tab="home">${svg('home')}<span>Trang chủ</span></button><button class="nav-btn ${state.tab==='favorites'?'active':''}" data-tab="favorites">${svg('heart')}<span>Đã lưu</span></button><button class="nav-main" aria-label="Đăng tin" title="Tính năng sắp có">${svg('plus')}</button><button class="nav-btn" title="Sắp có">${svg('message')}<span>Liên hệ</span></button><button class="nav-btn" title="Sắp có">${svg('user')}<span>Tài khoản</span></button></nav></div>`;attach();}
function attach(){document.querySelectorAll('[data-category]').forEach(el=>el.onclick=()=>{state.category=el.dataset.category;render()});document.querySelectorAll('[data-sort]').forEach(el=>el.onclick=()=>{state.sort=el.dataset.sort;render()});document.querySelectorAll('[data-favorite]').forEach(el=>el.onclick=e=>{e.stopPropagation();const id=Number(el.dataset.favorite);state.favorites.has(id)?state.favorites.delete(id):state.favorites.add(id);localStorage.setItem('macket-favorites',JSON.stringify([...state.favorites]));render()});document.querySelectorAll('[data-tab]').forEach(el=>el.onclick=()=>{state.tab=el.dataset.tab;render()});const inp=document.querySelector('#search');inp.oninput=e=>{state.query=e.target.value;document.querySelector('.listing-grid').innerHTML=cards();document.querySelector('.count').textContent=filtered().length+' tin';document.querySelectorAll('[data-favorite]').forEach(el=>el.onclick=ev=>{ev.stopPropagation();const id=Number(el.dataset.favorite);state.favorites.has(id)?state.favorites.delete(id):state.favorites.add(id);localStorage.setItem('macket-favorites',JSON.stringify([...state.favorites]));render()})};document.querySelector('#search-action').onclick=()=>inp.focus();}
render();
