import {build} from 'vite';
import {cp,mkdir,readFile,writeFile,readdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
await build();
const out=path.resolve('../../src/jetson_browser/static/whiteboard');
await cp('node_modules/@excalidraw/excalidraw/dist/prod/fonts',out+'/fonts',{recursive:true});
await cp('licenses/EXCALIDRAW-LICENSE.txt',out+'/EXCALIDRAW-LICENSE.txt');
let notices='Third-party dependency notices (locked npm build)\n';
const lock=JSON.parse(await readFile('package-lock.json','utf8'));
for(const [dir,metadata] of Object.entries(lock.packages)){
  if(!dir.startsWith('node_modules/'))continue;
  for(const name of ['LICENSE','LICENSE.md','LICENSE.txt','license','license.md','COPYING']){
    try{notices+='\n\n'+dir+'@'+metadata.version+'\n'+await readFile(path.join(dir,name),'utf8');break;}catch{}
  }
}
await writeFile(out+'/THIRD-PARTY-NOTICES.txt',notices);
const files={};
async function walk(dir){for(const item of await readdir(dir,{withFileTypes:true})){const name=path.join(dir,item.name);if(item.isDirectory())await walk(name);else files[path.relative(out,name)]=createHash('sha256').update(await readFile(name)).digest('hex');}}
await walk(out);
await writeFile('../../manifest-whiteboard-assets.json',JSON.stringify({component:'@excalidraw/excalidraw',version:'0.18.1',files},null,2)+'\n');
