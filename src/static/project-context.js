/* Navigation context only: never a project registry, import or generation request. */
const keys = ['project_id', 'job_id', 'character_id'];
export const validContextId = value => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
export function parseProjectContext(search = '') {
  const params = new URLSearchParams(search), result = {};
  for (const key of keys) {
    const values = params.getAll(key);
    if (values.length > 1 || (values.length === 1 && !validContextId(values[0])))
      throw new Error('This workspace link is invalid. Open a workspace from the navigation to start safely.');
    result[key] = values[0] ?? null;
  }
  return result;
}
export function workspaceLink(path, values = {}, search = '') {
  if (!['/', '/h3', '/characters', '/timeline'].includes(path))
    throw new Error('Invalid workspace destination.');
  const {project_id} = parseProjectContext(search), params = new URLSearchParams();
  if (project_id) params.set('project_id', project_id);
  for (const [key, value] of Object.entries(values)) {
    if (!keys.includes(key) || !validContextId(value))
      throw new Error('This workspace link is invalid.');
    params.set(key, value);
  }
  return path + (params.size ? '?' + params : '');
}


/* Keep classic studio controllers intact. Observe their explicit result/Character
 * links, adding navigation context only; downloads and frozen destinations stay alone. */
export function bindProjectNavigation({getSearch=()=>location.search,root=document,observe=true}={}) {
  const applied=new WeakMap();
  function refresh() {
    const search=getSearch();let valid=true;
    try{parseProjectContext(search);}catch{valid=false;}
    for(const link of root.querySelectorAll('a[href]')){
      const raw=link.getAttribute('href');
      if(!raw?.startsWith('/')||raw.startsWith('//'))continue;
      const previous=applied.get(link),original=previous?.value===raw?previous.original:raw;
      const url=new URL(original,location.href);
      if(!['/','/h3','/characters','/timeline'].includes(url.pathname))continue;
      try {
        const context=parseProjectContext(url.search);
        const values={};for(const key of ['project_id','job_id','character_id'])if(context[key])values[key]=context[key];
        const value=workspaceLink(url.pathname,values,valid?search:'')+url.hash;
        applied.set(link,{original,value});
        if(raw!==value)link.setAttribute('href',value);
      }catch{/* Invalid source links remain invalid; never normalize them into another asset. */}
    }
  }
  refresh();window.addEventListener('opengenjutsu:project-context',refresh);
  const observer=observe&&typeof MutationObserver!=='undefined'?new MutationObserver(refresh):null;
  observer?.observe(root,{subtree:true,childList:true,attributes:true,attributeFilter:['href']});
  return {refresh,dispose(){observer?.disconnect();window.removeEventListener?.('opengenjutsu:project-context',refresh);}};
}
