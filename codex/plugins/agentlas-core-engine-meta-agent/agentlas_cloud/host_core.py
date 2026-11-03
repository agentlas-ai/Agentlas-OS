"""Standalone native-host plugins with immutable runtime and skill generations.

Only this module's private marketplace is written. Host tools own registration
and activation; user configuration, legacy plugins and Desktop are never edited.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager

SKILLS = ('agentlas', 'hephaestus-network', 'hephaestus-cloud', 'hephaestus-upload', 'hephaestus-build')
OWNER = 'agentlas.os-host-plugin.v1'
PROMPT_MODULE = {'id':'host.standalone.skill-generation','revision':1,'stability':'versioned-content','changeTriggers':['release','runtime'],'order':0}
class Conflict(Exception): pass

def _json(value): return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
def _sha(value): return hashlib.sha256(value).hexdigest()
def _plain(path):
    for ancestor in (path,*path.parents):
        if ancestor.is_symlink(): raise Conflict('symlink_path')
def _read(path):
    _plain(path)
    if not path.is_file(): raise Conflict('owned_file_missing')
    return path.read_bytes()
def _namespace(home):
    if Path.home().resolve()!=home:raise Conflict('host_home_mismatch')
    from agentlas_cloud.update import _runtime_base
    return _runtime_base()

def _rename_new(source,target):
    # Publish a complete directory without replacing even an empty collision.
    if os.name=='nt':
        os.rename(source,target);return
    import ctypes
    library=ctypes.CDLL(None,use_errno=True)
    if sys.platform=='darwin':
        function=library.renamex_np
        function.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint]
        result=function(os.fsencode(source),os.fsencode(target),4)
    elif sys.platform.startswith('linux') and hasattr(library,'renameat2'):
        function=library.renameat2
        function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        result=function(-100,os.fsencode(source),-100,os.fsencode(target),1)
    else:raise Conflict('atomic_directory_publication_unavailable')
    if result:raise OSError(ctypes.get_errno(),'atomic_directory_publication_failed')


def _identity(root,home,host,kind):
    if host not in ('claude','codex') or kind not in ('core','memory','one'): raise Conflict('unsupported_host_or_plugin')
    root=Path(root).resolve(strict=True);home=Path(home).resolve(strict=True)
    _plain(root);_plain(home)
    base=_namespace(home)
    if not root.is_relative_to(base) or root==base: raise Conflict('standalone_runtime_required')
    if _read(base/'.agentlas-os-namespace-v1') != b'agentlas-os-namespace-v1\n': raise Conflict('namespace_ownership_unverified')
    release=_read(root/'RELEASE').decode().strip()
    if not re.fullmatch(r'v\d+\.\d+\.\d+',release): raise Conflict('release_invalid')
    if _read(root/'host_adapters/RELEASE').decode().strip()!=release: raise Conflict('adapter_release_mismatch')
    return root,home,release[1:]

def _payloads(root,host,kind):
    # A module launch avoids shell syntax differences across macOS/Windows/Linux.
    bootstrap='import os,runpy,sys; root=sys.argv.pop(1); os.environ["HEPHAESTUS_RUNTIME_BASE"]=sys.argv.pop(1); sys.path.insert(0,root); os.environ["HEPHAESTUS_RUNTIME_ROOT"]=root; os.environ["AGENTLAS_HOST_RUNTIME"]="standalone"; os.environ["PYTHONDONTWRITEBYTECODE"]="1"; runpy.run_module(sys.argv.pop(1),run_name="__main__")'
    module={'core':'agentlas_cloud','memory':'agentlas_cloud.memory_hook','one':'agentlas_cloud.standalone_one'}[kind]
    namespace=_namespace(Path.home().resolve())
    runtime_base=namespace if namespace==Path.home().resolve()/'.agentlas/os-runtime' else namespace.parent
    args=['-B','-c',bootstrap,str(root),str(runtime_base),module]
    outputs={}
    if kind=='core':
        for name in SKILLS:
            source=root/'skills'/name/'SKILL.md'
            if name=='hephaestus-build': source=root/'host_adapters/codex/plugins/agentlas-core-engine-meta-agent/skills'/name/'SKILL.md'
            content=_read(source).decode()
            quoted_root=root.as_posix().replace('\\','\\\\').replace('$','\\$').replace('`','\\`').replace(chr(34),'\\'+chr(34))
            for spelling in ('$HOME/.agentlas/runtime/current','${HOME}/.agentlas/runtime/current','~/.agentlas/runtime/current'):
                content=content.replace(spelling,quoted_root)
            # Every fallback stays in this generation; loss of the pinned
            # runtime must never silently switch to Desktop or a newer cache.
            for source_host in ('claude','codex'):
                content=content.replace('$HOME/.'+source_host+'/plugins/cache/agentlas-core-engine/hephaestus',quoted_root+'/host_adapters/'+source_host+'/plugins/agentlas-core-engine-meta-agent')
            import shlex
            content=content.replace('"./bin/hephaestus"','"'+quoted_root+'/bin/hephaestus"')
            content=re.sub(r'(?<![\w/])\./bin/hephaestus',lambda _:shlex.quote(str(root/'bin/hephaestus')),content)
            for variable in ('CODEX_PLUGIN_ROOT','CLAUDE_PLUGIN_ROOT','PLUGIN_ROOT'):
                content=content.replace('${'+variable+':-}',quoted_root+'/host_adapters/codex/plugins/agentlas-core-engine-meta-agent')
            content=content.replace('     "."','     "'+quoted_root+'"')
            if re.search(r'(?:runtime/current|plugins/cache|\$\{(?:CODEX_|CLAUDE_)?PLUGIN_ROOT)',content):raise Conflict('unpinned_skill_reference')
            outputs[f'skills/{name}/SKILL.md']=content.encode()
        from .host_command_catalog import command_payloads
        outputs.update(command_payloads(root,host,_read))
        outputs['.mcp.json']=_json({'mcpServers':{'hephaestus-network':{'command':sys.executable,'args':args+['mcp','serve']}}})
    else:
        # Hook commands are shell strings in both native hosts; quote for the
        # actual target OS, while runtime/MCP uses an argument vector above.
        import shlex
        vector=[sys.executable,*args]
        command=subprocess.list2cmdline(vector) if os.name=='nt' else shlex.join(vector)
        # One is injected once per session; the memory hook still refreshes project maps per prompt.
        events=[('SessionStart',15)]
        if kind=='memory':events+=[('UserPromptSubmit',60),('Stop',10)]
        hooks={event:[{'hooks':[{'type':'command','command':command+(' hook' if kind=='one' else '')+' --host '+host+' --event '+event+(' --memory-only' if kind=='memory' else ''),'timeout':timeout}]}] for event,timeout in events}
        outputs['hooks/hooks.json']=_json({'hooks':hooks})
    return outputs

@contextmanager
def _lock(path):
    # O_EXCL lock fails closed, including after interruption. No age-based steal.
    try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_BINARY",0),0o600)
    except FileExistsError:raise Conflict('installation_lock_exists')
    try:
        os.write(fd,_json({'owner':OWNER,'pid':os.getpid()}));os.fsync(fd)
        yield
    finally:
        os.close(fd);path.unlink()

def _verify_generation(generation):
    record=json.loads(_read(generation/'receipt.json'))
    if record.get('owner')!=OWNER: raise Conflict('generation_ownership_unverified')
    interpreter=record.get('pythonExecutable')
    if not isinstance(interpreter,str) or not Path(interpreter).is_file() or not os.access(interpreter,os.X_OK):raise Conflict('pinned_python_unavailable')
    expected=record.get('files',{})
    if not isinstance(expected,dict) or not expected: raise Conflict('generation_manifest_invalid')
    actual={str(p.relative_to(generation/'plugin')) for p in (generation/'plugin').rglob('*') if p.is_file() or p.is_symlink()}
    if actual!=set(expected): raise Conflict('generation_content_changed')
    for name,digest in expected.items():
        rel=Path(name)
        if rel.is_absolute() or '..' in rel.parts or _sha(_read(generation/'plugin'/rel))!=digest: raise Conflict('generation_content_changed')
    return record

def prepare_generation(root,home,host,*,plugin_kind='core'):
    root,home,release=_identity(root,home,host,plugin_kind)
    name='agentlas-os-'+plugin_kind
    market=home/'.agentlas/os-host-plugins'/plugin_kind/host
    _plain(market)
    marker=market/'owner.json'
    if market.exists():
        if json.loads(_read(marker))!={'owner':OWNER,'host':host,'kind':plugin_kind}: raise Conflict('marketplace_ownership_unverified')
    else:
        market.parent.mkdir(parents=True,exist_ok=True)
        # Stage the entire initially owned directory; never adopt existing data.
        stage=Path(tempfile.mkdtemp(prefix='.host-init-',dir=market.parent))
        (stage/'owner.json').write_bytes(_json({'owner':OWNER,'host':host,'kind':plugin_kind}))
        try: _rename_new(stage,market)
        except BaseException:
            shutil.rmtree(stage);raise
    with _lock(market/'install.lock'):
        files=_payloads(root,host,plugin_kind)
        digest=_sha(_json({'generatorRevision':1,'promptModule':PROMPT_MODULE,'runtime':str(root),'files':{p:_sha(b) for p,b in files.items()}}))
        version=release+'+os.'+digest[:12]
        generation=market/'generations'/digest
        manifest={'name':name,'version':version,'description':'Agentlas standalone '+plugin_kind+' runtime integration','author':{'name':'Agentlas'},'interface':{'displayName':'Agentlas OS '+plugin_kind,'shortDescription':'Standalone Agentlas runtime integration'}}
        if plugin_kind=='core':manifest.update({'skills':'./skills','mcpServers':'./.mcp.json'})
        for directory in ('.claude-plugin','.codex-plugin'): files[directory+'/plugin.json']=_json(manifest)
        receipt={'owner':OWNER,'pythonExecutable':sys.executable,'runtime':str(root),'host':host,'kind':plugin_kind,'version':version,'files':{p:_sha(b) for p,b in files.items()}}
        if generation.exists():
            if _verify_generation(generation)!=receipt: raise Conflict('generation_content_changed')
        else:
            generation.parent.mkdir(exist_ok=True)
            stage=Path(tempfile.mkdtemp(prefix='.staging-',dir=generation.parent))
            try:
                for path,data in files.items():
                    out=stage/'plugin'/path;out.parent.mkdir(parents=True,exist_ok=True)
                    with out.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
                (stage/'receipt.json').write_bytes(_json(receipt))
                _rename_new(stage,generation)
            finally:
                if stage.exists():shutil.rmtree(stage)
        relative='./generations/'+digest+'/plugin'
        if host=='claude':
            catalog={'name':name,'owner':{'name':'Agentlas'},'plugins':[{'name':name,'version':version,'source':relative}]}
            target=market/'.claude-plugin/marketplace.json'
        else:
            catalog={'name':name,'plugins':[{'name':name,'source':{'source':'local','path':relative},'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL','products':['CODEX']}}]}
            target=market/'.agents/plugins/marketplace.json'
        _plain(target)
        if target.exists():
            old=json.loads(_read(target));entry=old['plugins'][0];source=entry['source'];source=source['path'] if isinstance(source,dict) else source
            if old.get('name')!=name or len(old['plugins'])!=1 or not re.fullmatch(r'\./generations/[0-9a-f]{64}/plugin',source): raise Conflict('catalog_ownership_unverified')
            old_record=_verify_generation(market/source.removeprefix('./').removesuffix('/plugin'))
            if old_record['host']!=host or old_record['kind']!=plugin_kind:raise Conflict('catalog_ownership_unverified')
            expected_old=json.loads(_json(catalog))
            if host=='claude':expected_old['plugins'][0].update({'source':source,'version':old_record['version']})
            else:expected_old['plugins'][0]['source']['path']=source
            if old!=expected_old:raise Conflict('catalog_content_changed')
        target.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix='.catalog-',dir=target.parent)
        try:
            with os.fdopen(fd,'wb') as f:f.write(_json(catalog));f.flush();os.fsync(f.fileno())
            os.replace(tmp,target)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    return {'marketplace':market,'generation':generation,'name':name,'version':version,'runtime':str(root)}

def status(root,home,host,*,plugin_kind='core',_include_session=True):
    """Observe our own prepared files without starting or changing a host.

    Host CLI listing may initialize or rewrite its configuration. Session
    activation is process-local, so prepared files cannot prove connection.
    """
    try:
        root,home,_=_identity(root,home,host,plugin_kind)
        name='agentlas-os-'+plugin_kind;market=home/'.agentlas/os-host-plugins'/plugin_kind/host
        if not market.exists():return {'host':host,'status':'missing'}
        if json.loads(_read(market/'owner.json'))!={'owner':OWNER,'host':host,'kind':plugin_kind}:
            raise Conflict('marketplace_ownership_unverified')
        target=(market/'.claude-plugin/marketplace.json' if host=='claude'
                else market/'.agents/plugins/marketplace.json')
        if not target.exists():
            return {'host':host,'status':'partial','reason':'catalog_not_prepared','hostConfigurationChanged':False}
        catalog=json.loads(_read(target));entries=catalog.get('plugins')
        if catalog.get('name')!=name or not isinstance(entries,list) or len(entries)!=1:
            raise Conflict('catalog_ownership_unverified')
        entry=entries[0]
        if not isinstance(entry,dict) or entry.get('name')!=name:
            raise Conflict('catalog_ownership_unverified')
        source=entry.get('source')
        source=source.get('path') if isinstance(source,dict) else source
        if not isinstance(source,str) or not re.fullmatch(r'\./generations/[0-9a-f]{64}/plugin',source):
            raise Conflict('catalog_ownership_unverified')
        generation=market/source.removeprefix('./').removesuffix('/plugin')
        record=_verify_generation(generation)
        if record.get('host')!=host or record.get('kind')!=plugin_kind:
            raise Conflict('catalog_ownership_unverified')
        if host=='claude':
            expected={'name':name,'owner':{'name':'Agentlas'},'plugins':[{'name':name,'version':record['version'],'source':source}]}
        else:
            expected={'name':name,'plugins':[{'name':name,'source':{'source':'local','path':source},'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL','products':['CODEX']}}]}
        if catalog!=expected:raise Conflict('catalog_content_changed')
        if record.get('runtime')!=str(root):
            return {'host':host,'status':'outdated','version':record['version']}
        result={'host':host,'status':'partial','reason':'session_activation_not_observed',
                'version':record['version'],'runtime':str(root),'hostConfigurationChanged':False,
                'pluginDir':str(generation/'plugin')}
        if _include_session:
            result['session']=session_plan(root,home,host)
            if result['session'].get('status') in ('conflict','error'):
                result['status']=result['session']['status']
                result['reason']=result['session'].get('reason','session_verification_failed')
            if 'sessionCommand' in result['session']:result['sessionCommand']=result['session']['sessionCommand']
        return result
    except (Conflict,OSError,ValueError,KeyError,TypeError) as exc:
        return {'host':host,'status':'conflict' if isinstance(exc,Conflict) else 'error',
                'reason':str(exc) if isinstance(exc,Conflict) else type(exc).__name__}

def _session_launch_command(root,home,host):
    namespace=_namespace(home)
    runtime_base=namespace if namespace==home/'.agentlas/os-runtime' else namespace.parent
    bootstrap='import os,runpy,sys; root=sys.argv.pop(1); os.environ["HEPHAESTUS_RUNTIME_BASE"]=sys.argv.pop(1); os.environ["AGENTLAS_HOST_RUNTIME"]="standalone"; sys.path.insert(0,root); runpy.run_module("agentlas_cloud.host_session",run_name="__main__")'
    return [sys.executable,'-B','-c',bootstrap,str(root),str(runtime_base),'--host',host,'--']


def session_plan(root,home,host,*,prepare=False):
    """Compose one pinned session from current independent feature choices."""
    try:
        root,home,_=_identity(root,home,host,'core')
        from .feature_preferences import feature_enabled
        from .standalone_one import _snapshot, _root
        standalone_environment={**os.environ,'AGENTLAS_HOST_RUNTIME':'standalone'}
        selection={'one':_snapshot(_root())['on'], 'memory':feature_enabled('memory-hooks',environ=standalone_environment)}
        kinds=['core']+([kind for kind in ('one','memory') if selection[kind]] if host=='claude' else [])
        components=[]
        for kind in kinds:
            if prepare:
                info=prepare_generation(root,home,host,plugin_kind=kind)
                plugin=str(info['generation']/'plugin')
            else:
                observed=status(root,home,host,plugin_kind=kind,_include_session=False)
                plugin=observed.get('pluginDir')
                if not plugin:
                    return {'status':'partial','reason':'session_components_unprepared','missingComponent':kind,
                            'componentState':observed,'modelSessionObserved':False,'hostConfigurationChanged':False}
            record=_verify_generation(Path(plugin).parent)
            if record.get('runtime')!=str(root) or record.get('kind')!=kind or record.get('host')!=host:
                raise Conflict('session_component_identity_changed')
            components.append({'kind':kind,'pluginDir':plugin,'version':record['version']})
        if selection!={'one':_snapshot(_root())['on'], 'memory':feature_enabled('memory-hooks',environ=standalone_environment)}:
            raise Conflict('session_selection_changed')
        result={'status':'partial','reason':'session_activation_not_observed','components':components,
                'configurationSnapshot':selection,'modelSessionObserved':False,'hostConfigurationChanged':False,
                'sessionActivation':'not_started','newSessionRequired':True}
        # The equals form prevents this variadic option from consuming a
        # following prompt or subcommand; repeated options retain every plugin.
        if host=='claude':
            result['hostCommand']=['claude',*['--plugin-dir='+item['pluginDir'] for item in components]]
            result['sessionCommand']=_session_launch_command(root,home,host)
        else:
            from .codex_session import command
            result['hostCommand'],result['skillDiscovery']=command(root,home,components[0]['pluginDir'],prepare=prepare)
            result['sessionCommand']=_session_launch_command(root,home,host)
            result['coreToolSessionSupported']=True
            result['unappliedHookComponents']=[kind for kind in ('one','memory') if selection[kind]]
            if result['unappliedHookComponents']:
                result['reason']='codex_optional_hook_session_loader_unverified'
                result['requestedHooksApplied']=False
        return result
    except (Conflict,OSError,ValueError,KeyError,TypeError) as exc:
        return {'status':'conflict' if isinstance(exc,Conflict) else 'error',
                'reason':str(exc) if isinstance(exc,Conflict) else type(exc).__name__,
                'modelSessionObserved':False,'hostConfigurationChanged':False}


def install(root,home,host,*,plugin_kind='core'):
    """Prepare a session plugin without modifying host settings or registries.

    Native persistent installation races external editors on supported Claude
    versions. A matching previous digest is not a compare-and-swap primitive.
    Never turn a preflight check into permission to overwrite host settings.
    """
    try:
        info=prepare_generation(root,home,host,plugin_kind=plugin_kind)
        result={'host':host,'status':'partial','reason':'persistent_host_configuration_atomicity_unavailable','version':info['version'],'runtime':info['runtime'],'hostConfigurationChanged':False}
        result['session']=session_plan(root,home,host,prepare=True)
        if 'sessionCommand' in result['session']:
            result['sessionCommand']=result['session']['sessionCommand']
            result['sessionActivation']='not_started'
        elif host=='codex':
            result['reason']=result['session'].get('reason','session_plugin_loader_not_verified')
            if result['session'].get('status') in ('conflict','error'):result['status']=result['session']['status']
        return result
    except (Conflict,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        return {'host':host,'status':'conflict' if isinstance(exc,Conflict) else 'error','reason':str(exc) if isinstance(exc,Conflict) else type(exc).__name__}


def main():
    home=Path.home();root=Path(__file__).resolve().parent.parent
    rows=[install(root,home,host) for host in ('claude','codex') if shutil.which(host)]
    print(json.dumps({'status':'partial','hosts':rows,'otherHosts':'not_implemented'}))
    return 1
if __name__=='__main__':raise SystemExit(main())
