#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从真实页面扒页面骨架，产出可喂给 proto_from_snapshot.py 的结构化快照。

这是「原型图不许凭印象画」的机械保证：原型帧的每一列、每个字段、每个按钮,
都来自这里 dump 出的真实 DOM，而不是写 PRD 的人回忆出来的。

只读，不点提交、不改数据。可以点开弹窗（只看不填）。

前置：
  1. Chrome/Edge 已用 --remote-debugging-port=9222 启动（launch_chrome.py 可代劳）
  2. 该浏览器已登录目标系统（登录态由你自己登，本脚本不碰凭据）

用法：
    # 抓一个页面（最常用）
    python3 snapshot_page.py --base https://test1x.example.com \\
        --url /personManage/fieldSetting?customerId=123 --key ops-field --page p1

    # 抓一个页面 + 点开某个按钮后的弹窗，各出一份
    python3 snapshot_page.py --base https://test1x.example.com \\
        --url /personManage/fieldSetting --key ops-field --page p1 \\
        --open "新增字段" --page p2

    # 批量：给一个清单文件
    python3 snapshot_page.py --base https://test1x.example.com --plan plan.json

plan.json 形如：
    [{"page": "p1", "url": "/a/b", "name": "列表"},
     {"page": "p2", "url": "/a/b", "name": "新增", "open": "新增字段"},
     {"page": "p3", "url": "/c/d", "name": "详情", "tab": "基本信息"}]

输出：snapshot/<key>.json（结构见 assets/snapshot.schema.json）

退出码：0 成功 / 2 参数错误 / 3 测试环境校验失败 / 4 连不上浏览器 / 5 页面没抓到内容
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _compat  # noqa: E402
import cdp_boot  # noqa: E402


def connect(port=9222, fresh=True):
    """连上已在调试端口的浏览器。

    fresh=True 时新开一个专用标签页，不抢用户正在看的那个；
    抓取共用同一份浏览器 profile，所以登录态是现成的。
    """
    cdp = cdp_boot.load()
    try:
        cl = cdp.CDPClient(port=port, timeout=30)
    except TypeError:
        cl = cdp.CDPClient()

    if not fresh:
        cl.ensure_page()          # 内部已 connect_page
        return cl

    cl.connect_browser()
    r = cl.send("Target.createTarget", {"url": "about:blank"})
    tid = (r or {}).get("targetId")
    cl.close()
    if not tid:
        raise RuntimeError("新建标签页失败：%r" % (r,))
    time.sleep(0.4)
    cl.connect_page(tid)
    cl._prd_tab_id = tid
    return cl


def close_tab(cl):
    """抓完把这个专用标签页关掉，别在人家浏览器里堆一地。"""
    tid = getattr(cl, "_prd_tab_id", None)
    if not tid:
        return
    try:
        cl.close()
        cl.connect_browser()
        cl.send("Target.closeTarget", {"targetId": tid})
        cl.close()
    except Exception:  # noqa: BLE001
        pass

# ---------------------------------------------------------------- DOM 抽取

# 一个 JS 把所有要的东西一次捞完。整套逻辑只依赖 ant-design 的公共 class,
# 不认具体业务，所以任何后台都能跑。
SNAP_JS = r"""
(function(){
  var CL = function(s){ return (s==null?'':String(s)).replace(/\s+/g,' ').trim(); };
  var T  = function(e){ if(!e) return ''; return CL(e.innerText || e.textContent || ''); };
  var vis= function(e){ if(!e) return false; var r=e.getBoundingClientRect();
                        return r.width>0 && r.height>0; };
  var uniq = function(a){ var s={}, r=[]; for(var i=0;i<a.length;i++){
      var v=a[i]; if(!v || s[v]) continue; s[v]=1; r.push(v); } return r; };

  // 详情页的滚动发生在内部容器里（.detailLayout 之类）。只加 window.scrollY 会把
  // 底部的元素算到页面中段，导致「流程干预」跑到明细中间。必须把所有祖先的
  // scrollTop 加回来，才是真正的布局坐标。
  var _ALL = [].slice.call(document.querySelectorAll('*'));
  var _IDX = new WeakMap();
  _ALL.forEach(function(e, i){ _IDX.set(e, i); });
  var docIdx = function(e){ return _IDX.has(e) ? _IDX.get(e) : -1; };

  var absY = function(e){
    var y = e.getBoundingClientRect().top, p = e.parentElement;
    while(p){ y += p.scrollTop || 0; p = p.parentElement; }
    return Math.round(y + window.scrollY);
  };
  var absX = function(e){
    var x = e.getBoundingClientRect().left, p = e.parentElement;
    while(p){ x += p.scrollLeft || 0; p = p.parentElement; }
    return Math.round(x + window.scrollX);
  };

  var root = document.querySelector('.ant-modal-content')
          || document.querySelector('.ant-drawer-content')
          || document.querySelector('[role="dialog"]')
          || document.body;
  var inModal = root !== document.body;

  // ---- 标题与面包屑
  // 这个系统的类名不一定是标准 ant，所以按「内容像不像」兜底找
  var title = T(document.querySelector('.ant-page-header-heading-title'))
           || T(document.querySelector('[class*=pageTitle],[class*=headerTitle]'))
           || T(document.querySelector('h1'))
           || '';
  var desc = '';
  var ch = null;
  [].slice.call(document.querySelectorAll('[class*=contentHeader],[class*=pageHeader]')).forEach(function(e){
    if(ch) return;
    var r = e.getBoundingClientRect();
    if(r.top >= 0 && r.top < 220 && r.width > 300) ch = e;
  });
  if(ch){
    var c3 = ch.cloneNode(true);
    [].slice.call(c3.querySelectorAll('button,.ant-btn,[class*=headerTitle],[class*=pageTitle]'))
      .forEach(function(x){ x.remove(); });
    desc = T(c3).slice(0, 160);
  }
  var crumb = [].slice.call(document.querySelectorAll('.ant-breadcrumb li, .ant-breadcrumb span'))
              .map(T).filter(Boolean);
  if(!crumb.length){
    // 兜底：找含分隔符、文字短、在页面顶部的那一条
    var cands = document.querySelectorAll('div,span,nav');
    for(var i=0;i<cands.length && i<600;i++){
      var e = cands[i];
      if(!vis(e) || e.children.length > 6) continue;
      var r = e.getBoundingClientRect();
      if(r.top > 200) continue;
      var t = T(e);
      if(t && t.length >= 4 && t.length <= 40 && /[\/›>»]/.test(t)
         && t.split(/[\/›>»]/).length <= 4 && t.indexOf('：') < 0
         && r.height <= 32){
        crumb = t.split(/\s*[\/›>»]\s*/).filter(Boolean);
        break;
      }
    }
  }
  if(!title && crumb.length) title = crumb[crumb.length-1];

  // ---- 顶栏菜单（ant 标准结构，任何后台都有）
  var topNav = [];
  var hdr = document.querySelector('.ant-layout-header, header');
  if(hdr){
    [].slice.call(hdr.querySelectorAll('.ant-menu-item')).forEach(function(e){
      var t = T(e);
      if(!t || t.length > 12) return;
      topNav.push({t: t, on: (e.className||'').indexOf('ant-menu-item-selected') > -1});
    });
  }

  // ---- 侧栏菜单：ant 类名不可靠，用几何判据找「左侧窄高竖排」
  var sideNav = [], sideW = 0;
  (function(){
    var best = null, bestScore = -1;
    var all = document.querySelectorAll('div,ul,nav,aside');
    for(var i=0;i<all.length;i++){
      var e = all[i];
      if(e === root || root.contains(e)) { /* 弹窗里的不算，但不影响几何判据 */ }
      var r = e.getBoundingClientRect();
      if(r.width < 110 || r.width > 300 || r.height < 180) continue;
      if(r.left > 60) continue;
      // 必须真有菜单项，否则详情页左侧的内容区会被误判成侧栏
      var its = e.querySelectorAll('.ant-menu-item, .ant-menu-submenu-title');
      if(its.length < 2) continue;
      // 取最外层那个（子元素也要够多）
      var score = its.length * 100 - r.width;
      if(score > bestScore){ bestScore = score; best = e; sideW = Math.round(r.width); }
    }
    if(!best) return;
    // 只用 ant 的类，别用 li —— li.ant-menu-submenu 的 innerText 会把整个子菜单串进来
    [].slice.call(best.querySelectorAll('.ant-menu-submenu-title,.ant-menu-item'))
      .forEach(function(e){
        var t = T(e);
        if(!t || t.length > 20 || t.indexOf('\n') >= 0) return;
        var cn = e.className || '';
        var isTitle = cn.indexOf('ant-menu-submenu-title') > -1;
        // 层级看父级：挂在某个 submenu 的 ul 里的才是二级
        var inSub = !isTitle && !!(e.parentElement
                    && e.parentElement.closest && e.parentElement.closest('.ant-menu-submenu'));
        sideNav.push({
          t: t,
          sub: inSub,
          on: cn.indexOf('ant-menu-item-selected') > -1
        });
      });
    // 去掉重复项（外层 ul 和内层 li 会被同时选中）
    var seenS = {};
    sideNav = sideNav.filter(function(x){
      var k = (x.sub ? "1" : "0") + x.t;
      if(seenS[k]) return false;
      seenS[k] = 1; return true;
    });
  })();

  // ---- 页签
  var tabs = [].slice.call(document.querySelectorAll('.ant-tabs-tab')).filter(vis)
             .map(function(e){ return {t: T(e),
               on: (e.className||'').indexOf('active') > -1}; }).filter(function(x){return x.t;});

  // ---- 表单：按折叠面板分组，没面板就一组
  function fieldOf(fi){
    var lb = fi.querySelector('.ant-form-item-label');
    var name = T(lb).replace(/[:：]\s*$/,'');
    if(!name || name.length > 40) return null;
    var ctl = fi.querySelector('input:not([type=hidden]),textarea,.ant-select,.ant-picker,'
            + '.ant-radio-group,.ant-checkbox-group,.ant-upload-select,.ant-input-number');
    var ty = 'text';
    if(ctl){
      var cn = ctl.className || '';
      if(cn.indexOf('ant-select')>-1)       ty = 'select';
      else if(cn.indexOf('ant-picker')>-1)  ty = 'date';
      else if(cn.indexOf('ant-radio')>-1)   ty = 'radio';
      else if(cn.indexOf('ant-checkbox')>-1)ty = 'checkbox';
      else if(cn.indexOf('ant-upload')>-1)  ty = 'upload';
      else if(cn.indexOf('ant-input-number')>-1) ty = 'number';
      else if(ctl.tagName === 'TEXTAREA')   ty = 'textarea';
    }
    var it = {name: name, type: ty,
      required: !!fi.querySelector('.ant-form-item-required'),
      disabled: !!(fi.querySelector('.ant-select-disabled')
                 || fi.querySelector('input[disabled]')
                 || fi.querySelector('.ant-picker-disabled')),
      placeholder: ctl ? (ctl.placeholder || '') : '',
      value: ''};
    var opts = [].slice.call(fi.querySelectorAll('.ant-radio-wrapper,.ant-checkbox-wrapper')).map(T);
    if(opts.length) it.options = opts;
    var si = fi.querySelector('.ant-select-selection-item');
    if(si) it.value = T(si);
    else if(ctl && ctl.tagName === 'INPUT') it.value = ctl.value || '';
    var ex = fi.querySelector('.ant-form-item-extra');
    if(ex) it.hint = T(ex);
    return it;
  }

  var groups = [];
  var panels = [].slice.call(root.querySelectorAll('.ant-collapse-item')).filter(vis);
  // 面板头里往往混着「新增字段」这类操作按钮，要剥掉只留分组名
  function panelName(p){
    var hd = p.querySelector('.ant-collapse-header');
    if(!hd) return '';
    var c = hd.cloneNode(true);
    [].slice.call(c.querySelectorAll('button,.ant-btn,.anticon')).forEach(function(x){ x.remove(); });
    var t = T(c);
    // 「基本信息 新增字段」这种把尾巴上的动作词削掉
    return t.replace(/\s*(新增|添加|编辑|删除|配置|管理|批量导入|导出)[^\s]*\s*$/, '').trim();
  }
  if(panels.length){
    panels.forEach(function(p){
      var items = [].slice.call(p.querySelectorAll('.ant-form-item')).filter(vis)
                  .map(fieldOf).filter(Boolean);
      groups.push({name: panelName(p) || '(未命名分组)',
                   open: (p.className||'').indexOf('active') > -1, fields: items});
    });
  } else {
    var items = [].slice.call(root.querySelectorAll('.ant-form-item')).filter(vis)
                .map(fieldOf).filter(Boolean);
    if(items.length) groups.push({name: '', open: true, fields: items});
  }

  // ---- 表格：一张表一份，别把多张表的表头串成一坨
  // 注意 ant-table 是「表头一个 table、表体另一个 table」的分离结构，
  // 直接按 <table> 遍历会得到「有 th 没 td」和「有 td 没 th」两个半截，
  // 结果什么都抽不出来。所以先按 .ant-table 容器整体处理。
  var tables = [];

  function rowsOf(scope, nCol){
    var trs = [].slice.call(scope.querySelectorAll('tbody tr, tr')).filter(vis);
    trs = trs.filter(function(tr){
      var td = tr.querySelectorAll('td');
      if(!td.length) return false;
      var txt = T(td[0]);
      if(td.length === 1 && /暂无|没有数据|无数据|No data/i.test(txt)) return false;
      return td.length >= Math.max(2, nCol * 0.5);
    });
    var out = [];
    trs.slice(0, 3).forEach(function(tr){
      out.push([].slice.call(tr.querySelectorAll('td')).map(function(td){
        var tg = td.querySelector('.ant-tag,.ant-badge-status-text');
        return {text: T(td).slice(0, 40), tag: tg ? T(tg) : ''};
      }));
    });
    return {rows: out, count: trs.length};
  }

  function capOf(node){
    var box = node.closest('.ant-card,.ant-collapse-item,.ant-tabs-tabpane') || node.parentElement;
    if(!box) return '';
    var hd2 = box.querySelector('.ant-card-head-title,.ant-collapse-header');
    if(!hd2) return '';
    var c2 = hd2.cloneNode(true);
    [].slice.call(c2.querySelectorAll('button,.ant-btn,.anticon')).forEach(function(x){ x.remove(); });
    return T(c2).replace(/\s*(新增|添加|编辑|删除|配置|管理)[^\s]*\s*$/,'').trim();
  }

  var boxes = [].slice.call(root.querySelectorAll('.ant-table')).filter(vis);
  if(boxes.length){
    boxes.forEach(function(box){
      var ths = [].slice.call(box.querySelectorAll('.ant-table-thead th')).filter(vis)
                .map(T).filter(Boolean);
      if(!ths.length) ths = [].slice.call(box.querySelectorAll('thead th')).map(T).filter(Boolean);
      if(!ths.length) return;
      var body = box.querySelector('.ant-table-body, .ant-table-content') || box;
      var r = rowsOf(body, ths.length);
      var br = box.getBoundingClientRect();
      tables.push({caption: capOf(box), th: ths, rows: r.rows, rowCount: r.count,
                   y: absY(box), x: absX(box)});
    });
  } else {
    // 普通 table（没有 ant-table 包裹）
    [].slice.call(root.querySelectorAll('table')).filter(vis).forEach(function(tb){
      var ths = [].slice.call(tb.querySelectorAll('thead th, tr:first-child th'))
                .filter(vis).map(T).filter(Boolean);
      if(!ths.length) return;
      var r = rowsOf(tb, ths.length);
      var br2 = tb.getBoundingClientRect();
      tables.push({caption: capOf(tb), th: ths, rows: r.rows, rowCount: r.count,
                   y: absY(tb), x: absX(tb)});
    });
  }
  var hasTable = tables.length > 0;

  // ---- 按钮
  // 页脚操作条：详情页右下角的「流程干预」就在 <footer class="detailLayoutFooter"> 里，
  // 不是 position:fixed，只能看祖先标签/类名。
  var isFloat = function(e){
    var p = e.parentElement, n = 0;
    while(p && n++ < 10){
      var cs2 = getComputedStyle(p);
      if(cs2.position === 'fixed' || cs2.position === 'sticky') return true;
      if(p.tagName === 'FOOTER') return true;
      var cn2 = (p.className || '').toString().toLowerCase();
      if(cn2.indexOf('footer') >= 0 && cn2.indexOf('page') < 0) return true;
      p = p.parentElement;
    }
    return false;
  };

  var btns = [].slice.call(root.querySelectorAll('button')).filter(vis).map(function(b){
    var t = T(b); if(!t || t.length > 24) return null;
    var cn = b.className || '';
    var br = b.getBoundingClientRect();
    return {text: t,
      x: absX(b), y: absY(b), w: Math.round(br.width), idx: docIdx(b),
      primary: cn.indexOf('ant-btn-primary') > -1 || cn.indexOf('ant-btn-dangerous') > -1,
      danger : cn.indexOf('ant-btn-dangerous') > -1,
      link   : cn.indexOf('ant-btn-link') > -1 || cn.indexOf('ant-btn-text') > -1,
      float  : isFloat(b),
      disabled: !!b.disabled};
  }).filter(Boolean);

  // ---- 分页与总数
  var total = '';
  var tot = root.querySelector('.ant-pagination-total-text');
  if(tot) total = T(tot);
  var pager = [].slice.call(root.querySelectorAll('.ant-pagination-item')).map(T).filter(Boolean);
  // 有些系统不用 ant-pagination，兜底找「共 N 条」
  if(!total){
    var hit = (document.body.innerText || '').match(/共\s*[\d,]+\s*[条个项]/);
    if(hit) total = hit[0];
  }

  // ---- 空态
  var empty = '';
  var em = root.querySelector('.ant-empty-description');
  if(em) empty = T(em);

  // ---- 卡片标题
  var cards = uniq([].slice.call(root.querySelectorAll(
      '.ant-card-head-title,.ant-descriptions-title,.ant-divider-inner-text')).filter(vis).map(T));

  // ---- 描述型详情：详情页基本都是 label-value 对，不是 form-item
  // 不抽这块，详情页的原型会是空白
  var details = [];
  [].slice.call(root.querySelectorAll('.ant-descriptions-item')).forEach(function(it){
    var lb = it.querySelector('.ant-descriptions-item-label');
    var ct = it.querySelector('.ant-descriptions-item-content');
    var k = T(lb).replace(/[:：]\s*$/, '');
    var v = T(ct);
    if(k) details.push({k: k.slice(0, 30), v: v.slice(0, 80)});
  });
  // 有些详情页用 ant-form 的只读态渲染，补一层
  if(!details.length){
    [].slice.call(root.querySelectorAll('.ant-form-item')).forEach(function(fi){
      var lb = fi.querySelector('.ant-form-item-label');
      var ct = fi.querySelector('.ant-form-item-control');
      var k = T(lb).replace(/[:：]\s*$/, '');
      var v = T(ct);
      if(k && v && v.length < 120) details.push({k: k.slice(0, 30), v: v.slice(0, 80)});
    });
  }
  // 兜底：有些详情页整页是内联样式的 div/span，没有任何语义 class，
  // 只能扫「标签：值」这种文本模式把字段捞出来
  (function(){
    var seenK = {};
    details.forEach(function(d){ seenK[d.k] = 1; });
    var extra = [];
    [].slice.call(root.querySelectorAll('span,div,p,li')).forEach(function(e){
      if(e.children.length > 2) return;         // 只看叶子
      var t = T(e);
      if(!t || t.length > 100) return;
      var m = t.match(/^([^：:\s]{1,14})[：:]\s*(.+)$/);
      if(!m) return;
      var k = m[1].trim(), v = m[2].trim();
      if(!k || !v || seenK[k]) return;
      seenK[k] = 1;
      extra.push({k: k, v: v.slice(0, 80)});
    });
    details = details.concat(extra);
  })();

  // 卡片/分块标题，详情页靠它们分段
  var blocks = uniq([].slice.call(root.querySelectorAll(
      '.ant-descriptions-title,.ant-card-head-title,.ant-divider-inner-text,[class*=sectionTitle],[class*=blockTitle]'))
    .filter(vis).map(T));
  // 这种页面同样没有标题 class，退化为「不含冒号的短文本」
  if(blocks.length < 2){
    var bs = [];
    [].slice.call(root.querySelectorAll('span,div')).forEach(function(e){
      if(e.children.length > 1) return;
      var t = T(e);
      if(!t || t.length > 12 || /[：:]/.test(t)) return;
      if(/^(查看|编辑|操作|返回|提交|取\s*消|确\s*定)$/.test(t)) return;
      bs.push(t);
    });
    blocks = uniq(bs).slice(0, 24);
  }

  // ---- 弹窗/抽屉里的自定义列表（既不是 form-item 也不是 table 的那种）
  // 例：管理分组弹窗里「基本信息 / 固定分组 / 基本信息」这种行
  var listItems = [];
  if(inModal){
    var holders = [];
    var cs = root.querySelectorAll('div,li');
    for(var i2=0;i2<cs.length;i2++){
      var e2 = cs[i2];
      var r2 = e2.getBoundingClientRect();
      if(r2.height < 22 || r2.height > 90) continue;
      if(r2.width < 180) continue;
      var t2 = T(e2);
      if(!t2 || t2.length < 2 || t2.length > 80) continue;
      // 只留最内层那一个，别把整个弹窗当一行
      if(e2.querySelectorAll('div,li').length > 3) continue;
      holders.push({t: t2, y: Math.round(r2.top)});
    }
    // 按纵向位置排序 + 去重 + 去掉被别的行包含的
    holders.sort(function(a,b){ return a.y - b.y; });
    var seenL = {};
    holders.forEach(function(x){
      var k = x.t;
      if(seenL[k]) return;
      // 已经有了包含这行文字的更短条目，就跳过
      for(var j=0;j<listItems.length;j++){
        if(listItems[j].indexOf(k) >= 0) return;
      }
      seenL[k] = 1;
      listItems.push(k);
    });
    listItems = listItems.slice(0, 24);
    // 标题和底部按钮不是列表项，剔掉
    var dtitle = T(root.querySelector('.ant-modal-title,.ant-drawer-title'));
    listItems = listItems.filter(function(t){
      if(dtitle && t === dtitle) return false;
      if(/^(取\s*消|确\s*定|关\s*闭|保\s*存|提\s*交|返\s*回|上一步|下一步)/.test(t)) return false;
      return true;
    });
  }

  // ---- 带样式的文本行：详情页全是内联样式，只能靠「位置 + 字号字重」还原布局
  var layoutRows = (function(){
    var items = [];
    [].slice.call(document.querySelectorAll('span,div,h1,h2,h3,h4')).forEach(function(e){
      if(e.children.length > 0) return;                 // 只要叶子
      if(e.closest('.ant-table')) return;               // 表格内容另行抽取
      var t = T(e);
      if(!t || t.length > 120) return;
      var r = e.getBoundingClientRect();
      if(r.width < 2 || r.height < 2) return;
      var cs = getComputedStyle(e);
      // 值有没有「框」（只读输入框那种灰底/边框）：自己或父级带底色/边框就算
      var bg = cs.backgroundColor || '', bw = parseFloat(cs.borderTopWidth) || 0;
      var boxed = (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') || bw > 0;
      if(!boxed && e.parentElement){
        var ps = getComputedStyle(e.parentElement);
        var pbg = ps.backgroundColor || '', pbw = parseFloat(ps.borderTopWidth) || 0;
        boxed = (pbg && pbg !== 'rgba(0, 0, 0, 0)' && pbg !== 'transparent') || pbw > 0;
      }
      items.push({t: t, y: absY(e), x: absX(e), w: Math.round(r.width), idx: docIdx(e),
                  fs: Math.round(parseFloat(cs.fontSize) || 0),
                  fw: parseInt(cs.fontWeight) || 400, box: boxed});
    });
    // 表单标签：antd 的 label 里常再包一层 span，不算叶子，会漏掉
    // 「出款状态」「出款说明」这种只有标签没有值的字段
    [].slice.call(document.querySelectorAll('.ant-form-item-label label, .ant-form-item-label')).forEach(function(e){
      if(!vis(e)) return;
      var t = T(e);
      if(!t || t.length > 16) return;
      if(items.some(function(x){ return x.t === t && Math.abs(x.y - absY(e)) < 6; })) return;
      var cs5 = getComputedStyle(e);
      items.push({t: t, y: absY(e), x: absX(e), w: Math.round(e.getBoundingClientRect().width),
                  idx: docIdx(e), fs: Math.round(parseFloat(cs5.fontSize) || 0),
                  fw: parseInt(cs5.fontWeight) || 400, box: false,
                  chk: false, dis: false});
    });

    // 输入框的值：编辑态 / 抽屉里的字段值在 input.value 里，不是文本节点，
    // 不抓的话「打款账户」「期望付款日期」会只剩标签没有值
    [].slice.call(document.querySelectorAll('input, textarea')).forEach(function(e){
      if(!vis(e)) return;
      if((e.type||'') === 'hidden') return;
      var v = (e.value || '').trim();
      if(!v) return;
      if(e.type === 'radio' || e.type === 'checkbox') return;
      if(items.some(function(x){ return Math.abs(x.y - absY(e)) < 6 && Math.abs(x.x - absX(e)) < 6; })) return;
      var cs4 = getComputedStyle(e);
      var bw4 = parseFloat(cs4.borderTopWidth) || 0;
      items.push({t: v, y: absY(e), x: absX(e), w: Math.round(e.getBoundingClientRect().width),
                  idx: docIdx(e), fs: Math.round(parseFloat(cs4.fontSize) || 0),
                  fw: parseInt(cs4.fontWeight) || 400,
                  box: bw4 > 0 || (cs4.backgroundColor && cs4.backgroundColor !== 'rgba(0, 0, 0, 0)'),
                  chk: false, dis: !!e.disabled, isInput: true});
    });

    // 单选框：选中/禁用状态必须抓，否则「打款方式」这种会画错选中项
    [].slice.call(document.querySelectorAll('.ant-radio-wrapper, [class*=radio-wrapper]')).forEach(function(e){
      if(!vis(e)) return;
      var t = T(e);
      if(!t || t.length > 14) return;
      var cn3 = (e.className || '').toString();
      var chk = cn3.indexOf('checked') > -1;
      var dis = cn3.indexOf('disabled') > -1;
      var dup = null;
      items.forEach(function(x){
        if(x.t === t && Math.abs(x.y - absY(e)) < 8) dup = x;
      });
      if(dup){ dup.chk = chk; dup.dis = dis; return; }
      var cs3 = getComputedStyle(e);
      items.push({t: t, y: absY(e), x: absX(e), w: Math.round(e.getBoundingClientRect().width),
                  idx: docIdx(e), fs: Math.round(parseFloat(cs3.fontSize) || 0),
                  fw: parseInt(cs3.fontWeight) || 400, box: false, chk: chk, dis: dis});
    });

    // 状态标签常是 span>svg+文字，没有纯文字叶子，单独补一遍
    [].slice.call(document.querySelectorAll('.ant-tag,[class*=StatusTag],[class*=statusTag]')).forEach(function(e){
      if(!vis(e)) return;
      var t = T(e);
      if(!t || t.length > 12) return;
      if(items.some(function(x){ return x.t === t && Math.abs(x.y - absY(e)) < 8; })) return;
      var cs = getComputedStyle(e);
      items.push({t: t, y: absY(e), x: absX(e), w: Math.round(e.getBoundingClientRect().width),
                  idx: docIdx(e), fs: Math.round(parseFloat(cs.fontSize) || 0),
                  fw: parseInt(cs.fontWeight) || 400});
    });

    items.sort(function(a,b){ return a.y - b.y || a.x - b.x; });
    // 按 y 聚成行
    var rows = [], cur = [], ly = null;
    items.forEach(function(it){
      if(ly === null || Math.abs(it.y - ly) <= 4){ cur.push(it); if(ly===null) ly = it.y; }
      else { rows.push(cur); cur = [it]; ly = it.y; }
    });
    if(cur.length) rows.push(cur);
    return rows.map(function(r){
      r.sort(function(a,b){ return a.x - b.x; });
      return r.map(function(x){
        return {t: x.t, x: x.x, y: x.y, w: x.w, fs: x.fs, fw: x.fw,
                idx: x.idx, box: x.box,
                chk: !!x.chk, dis: !!x.dis, isInput: !!x.isInput};
      });
    });
  })();

  // ---- 布局度量：给原型帧定列宽用
  function w(sel){ var e = root.querySelector(sel); return e ? Math.round(e.getBoundingClientRect().width) : 0; }
  var dims = {sidebar: sideW || w('.ant-layout-sider') || w('aside'),
              header:  w('.ant-layout-header') || w('header'),
              modal:   w('.ant-modal-content')};

  return JSON.stringify({
    url: location.href, title: title, desc: desc, crumb: crumb, tabs: tabs,
    inModal: inModal, hasTable: hasTable,
    topNav: topNav, sideNav: sideNav,
    groups: groups, tables: tables, buttons: btns,
    total: total, pager: pager, empty: empty, cards: cards, dims: dims,
    listItems: listItems, details: details, blocks: blocks, layoutRows: layoutRows,
    dialogTitle: inModal ? T(root.querySelector('.ant-modal-title,.ant-drawer-title')) : ''
  });
})()
"""


# ---------------------------------------------------------------- 动作

def ev(cl, js):
    r = cl.evaluate(js)
    if isinstance(r, dict) and "value" in r:
        return r["value"]
    return r


def esc_js(s):
    return json.dumps(s, ensure_ascii=False)


CLICK_BTN_JS = r"""
(function(){
  var want = %s;
  var bs = document.querySelectorAll('button, .ant-btn, [role="button"], a');
  for(var i=0;i<bs.length;i++){
    var t = (bs[i].innerText || '').replace(/\s+/g,'').trim();
    if(t !== want && t.indexOf(want) < 0) continue;
    var r = bs[i].getBoundingClientRect();
    if(r.width < 4 || r.height < 4) continue;
    if(r.top < 0 || r.bottom > innerHeight){
      bs[i].scrollIntoView({block:'center'});
      r = bs[i].getBoundingClientRect();
    }
    return JSON.stringify({x: Math.round(r.x + r.width/2),
                           y: Math.round(r.y + r.height/2),
                           disabled: !!bs[i].disabled});
  }
  return 'NOTFOUND';
})()
"""

CLICK_TAB_JS = r"""
(function(){
  var want = %s;
  var es = document.querySelectorAll('[role="tab"], .ant-tabs-tab');
  for(var i=0;i<es.length;i++){
    var t = (es[i].innerText || '').replace(/\s+/g,' ').trim();
    if(t !== want && t.indexOf(want) < 0) continue;
    var r = es[i].getBoundingClientRect();
    if(r.width < 4) continue;
    return JSON.stringify({x: Math.round(r.x + r.width/2),
                           y: Math.round(r.y + r.height/2), disabled: false});
  }
  return 'NOTFOUND';
})()
"""


def real_click(cl, finder_js, want, wait=1.6):
    """用真鼠标事件点。

    React 的 onClick 对 el.click() 经常不响应（有些组件拦了合成事件），
    必须走 Input.dispatchMouseEvent 才能触发，这是踩过的坑。
    """
    raw = ev(cl, finder_js % esc_js(want))
    if raw == "NOTFOUND" or not raw:
        return "NOTFOUND"
    try:
        p = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:  # noqa: BLE001
        return "BADRECT"
    if p.get("disabled"):
        return "DISABLED"
    for t in ("mouseMoved", "mousePressed", "mouseReleased"):
        extra = {} if t == "mouseMoved" else {"button": "left", "clickCount": 1}
        cl.send("Input.dispatchMouseEvent", dict(type=t, x=p["x"], y=p["y"], **extra))
    time.sleep(wait)
    return "OK"

CLOSE_JS = r"""
(function(){
  var b = document.querySelector('.ant-modal-close, .ant-drawer-close');
  if(b){ b.click(); return 'OK'; }
  return 'NONE';
})()
"""


CLICK_VERIFY_JS = r"""
(function(){
  var want = %s;
  var es = document.querySelectorAll('[role="tab"], .ant-tabs-tab');
  for(var i=0;i<es.length;i++){
    var t = (es[i].innerText || '').replace(/\s+/g,' ').trim();
    if(t !== want && t.indexOf(want) < 0) continue;
    var cls = es[i].className || '';
    var on = es[i].getAttribute('aria-selected') === 'true'
             || /(^|\s)(active|ant-tabs-tab-active)(\s|$)/.test(cls);
    return on;
  }
  return null;
})()
"""


def tab_is_active(cl, name):
    """页签到底选上没有。找不到这个页签返回 None。"""
    try:
        return ev(cl, CLICK_VERIFY_JS % esc_js(name))
    except Exception:  # noqa: BLE001
        return None


def wait_ready(cl, timeout=20):
    """等页面从 loading 变成有内容。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            n = ev(cl, "(function(){return document.querySelectorAll('button,table th,.ant-form-item').length})()")
            if isinstance(n, int) and n > 2:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return False


def scroll_through(cl, step=700, pause=0.25, max_steps=40):
    """从顶滚到底再回顶。

    后台很多区块是滚动到才渲染（懒加载 / 虚拟列表 / 折叠面板），
    不滚一遍直接抽会漏内容。用户明确要求长页面必须滚到底。
    """
    total = ev(cl, "(function(){return Math.max(document.body.scrollHeight,"
                   "document.documentElement.scrollHeight)})()") or 0
    vh = ev(cl, "window.innerHeight") or 900
    y, steps = 0, 0
    while y < total and steps < max_steps:
        y += step
        ev(cl, "window.scrollTo(0, %d)" % y)
        time.sleep(pause)
        steps += 1
        new_total = ev(cl, "(function(){return Math.max(document.body.scrollHeight,"
                           "document.documentElement.scrollHeight)})()") or total
        if new_total > total:
            total = new_total        # 滚出新内容了，继续
    ev(cl, "window.scrollTo(0, 0)")
    time.sleep(0.4)
    return {"height": total, "viewport": vh, "steps": steps}


def snap_one(cl, base, spec, out_shots, shot_prefix, settle=2.5):
    """抓一帧。spec = {page, url, name, open?, tab?, settle?}"""
    url = spec["url"]
    full = url if url.startswith("http") else base.rstrip("/") + "/" + url.lstrip("/")
    cl.navigate(full, timeout=30)
    time.sleep(1.0)
    wait_ready(cl)
    wait = float(spec.get("settle", settle) or 0)
    if wait:
        time.sleep(wait)

    # 导航之后、抽取之前要做的动作（比如先筛一次再抓）。
    # 列表页的默认排序常常不是我们要看的那类数据——不筛就只能抓到第一页第一行。
    after = spec.get("_after_nav")
    if callable(after):
        after(cl)
        time.sleep(float(spec.get("_after_wait", 2.5)))

    for step, sel in (("tab", spec.get("tab")), ("open", spec.get("open"))):
        if not sel:
            continue
        r = real_click(cl, CLICK_TAB_JS if step == "tab" else CLICK_BTN_JS, sel)
        if r != "OK":
            print("    ! 点「%s」失败：%s" % (sel, r), flush=True)
        wait_ready(cl, timeout=12)
        # 页签内容是懒加载的，wait_ready 常被页面其他区块满足，这里再稳一手
        time.sleep(3.0 if step == "tab" else 1.2)
        if step == "tab":
            # 点完必须核对真的选中了。多页签页面上「点了但没切」是静默失败：
            # 抽出来的结构照样有内容，只有跟截图比对才发现四帧一模一样。
            for attempt in range(2):
                if tab_is_active(cl, sel) is not False:
                    break
                print("    ! 「%s」没选中，重点一次" % sel, flush=True)
                time.sleep(1.2)
                real_click(cl, CLICK_TAB_JS, sel)
                time.sleep(2.5)
            if tab_is_active(cl, sel) is False:
                raise RuntimeError(
                    "页签「%s」点了两次都没选中，抓到的会是别的页签内容，先别往下走" % sel)


    # 滚一遍再抽：长页面 / 懒加载区块不滚到位会漏
    if spec.get("scroll", True):
        info = scroll_through(cl)
        if info["height"] > info["viewport"] * 1.5:
            print("        （长页面 %.0f px，已滚到底再回顶）" % info["height"], flush=True)

    raw = ev(cl, SNAP_JS)
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:  # noqa: BLE001
        return {"page": spec.get("page"), "name": spec.get("name"),
                "error": "DOM 抽取失败：%s" % exc}

    d["page"] = spec.get("page") or ("p%d" % (len(out_shots) + 1))
    d["name"] = spec.get("name") or d.get("title") or d["page"]
    d["route"] = url
    d["openedBy"] = spec.get("open") or ""
    d["tab"] = spec.get("tab") or ""

    # 截图存档，作为「这帧确实来自实拍」的旁证
    try:
        shot = os.path.join(out_shots, "%s-%s.png" % (shot_prefix, d["page"]))
        cl.screenshot(shot)
        d["shot"] = os.path.basename(shot)
    except Exception:  # noqa: BLE001
        d["shot"] = ""

    if spec.get("open"):
        ev(cl, CLOSE_JS)
        time.sleep(0.6)
    return d


# ---------------------------------------------------------------- 体检

def summarize(d):
    """打一行人类可读摘要，好判断抓没抓到。"""
    if d.get("error"):
        return "✗ " + d["error"]
    nf = sum(len(g["fields"]) for g in d.get("groups") or [])
    nt = len(d.get("tables") or [])
    ncol = sum(len(t["th"]) for t in d.get("tables") or [])
    bits = []
    if d.get("inModal"):
        bits.append("弹窗「%s」" % (d.get("dialogTitle") or "?") )
    if d.get("tabs"):
        bits.append("%d 个页签" % len(d["tabs"]))
    if nt:
        bits.append("%d 张表 / %d 列" % (nt, ncol))
    if nf:
        bits.append("%d 个字段" % nf)
    if d.get("listItems"):
        bits.append("%d 条列表项" % len(d["listItems"]))
    if d.get("buttons"):
        bits.append("%d 个按钮" % len(d["buttons"]))
    # 详情页往往没有表格和表单，只有「文字行」，别把它误报成没抓到
    nr = len(d.get("layoutRows") or [])
    if nr:
        bits.append("%d 行结构（详情页布局）" % nr)
    if not bits:
        bits.append("**什么都没抽到**")
    return "、".join(bits)


def main():
    ap = argparse.ArgumentParser(
        description="从真实页面扒骨架，产出原型帧的结构化来源",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--base", required=True,
                    help="站点根地址，如 https://test1x.example.com（必须是测试环境）")
    ap.add_argument("--key", help="输出文件名（不含扩展名），默认取 --page 或 plan 名")
    ap.add_argument("--out", default="snapshot", help="输出目录，默认 ./snapshot")
    ap.add_argument("--shots", default=None, help="截图目录，默认 <out>/shots")
    ap.add_argument("--url", help="要抓的页面路径，如 /a/b?x=1")
    ap.add_argument("--page", help="帧编号，默认 p1")
    ap.add_argument("--name", help="帧名字，默认取页面标题")
    ap.add_argument("--open", help="进入后点这个按钮（抓弹窗），如「新增字段」")
    ap.add_argument("--tab", help="进入后点这个页签")
    ap.add_argument("--plan", help="批量清单 JSON，见文件头说明")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--settle", type=float, default=2.5,
                    help="wait_ready 之后再等几秒，详情页内容常晚到")
    ap.add_argument("--fresh", action="store_true",
                    help="清空重来。默认是增量合并：同 key 多次抓按页号合并")
    ap.add_argument("--allow-non-test", action="store_true",
                    help="跳过测试环境校验（只在你清楚风险时用）")
    a = ap.parse_args()

    # 硬约束：只允许测试环境
    if not a.allow_non_test:
        import check_test_env as CTE
        ok, why = CTE.judge(a.base)
        if not ok:
            sys.exit("✗ 测试环境校验不通过：\n%s\n"
                     "  本 skill 只允许读测试环境。确认无误可加 --allow-non-test。"
                     % why)

    # 收集要抓的帧
    if a.plan:
        try:
            specs = json.load(open(a.plan, encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            sys.exit("✗ 读不了 plan：%s" % exc)
        if isinstance(specs, dict):
            specs = specs.get("pages") or []
    elif a.url:
        specs = [{"url": a.url, "page": a.page or "p1", "name": a.name,
                  "open": a.open, "tab": a.tab}]
    else:
        sys.exit("✗ 要么给 --url，要么给 --plan")

    key = a.key or (specs[0].get("page") if len(specs) == 1 else None) or "snapshot"
    key = re.sub(r"[^\w.-]", "-", key)

    out_dir = os.path.abspath(a.out)
    shot_dir = os.path.abspath(a.shots or os.path.join(out_dir, "shots"))
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(shot_dir, exist_ok=True)

    try:
        cl = connect(a.port)
    except Exception as exc:  # noqa: BLE001
        sys.exit("✗ 连不上浏览器（端口 %d）：%s\n"
                 "  先起一个带调试端口的 Chrome：%s %s"
                 % (a.port, exc, _compat.python_cmd(),
                    os.path.join(HERE, "launch_chrome.py")))

    print("目标 %s，共 %d 帧\n" % (a.base, len(specs)))
    frames = []
    try:
        for i, spec in enumerate(specs, 1):
            print("[%d/%d] %-10s %s%s"
                  % (i, len(specs), spec.get("page") or "p%d" % i, spec["url"],
                     ("  点「%s」" % spec["open"]) if spec.get("open") else ""), flush=True)
            d = snap_one(cl, a.base, spec, shot_dir, key, a.settle)
            print("        → %s" % summarize(d), flush=True)
            frames.append(d)
    finally:
        close_tab(cl)

    doc = {
        "schema": "snapshot/1.0",
        "engine": "system-to-prd@2.0",
        "key": key,
        "base": a.base,
        "capturedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "frames": frames,
    }
    p = os.path.join(out_dir, "%s.json" % key)

    # 增量合并：同一个 key 常要分几次抓（主页面 / 详情 / 弹窗），
    # 每次都整个覆盖的话前面就白抓了。按 page 号合并，新的覆盖旧的。
    if os.path.exists(p) and not a.fresh:
        try:
            old = json.load(open(p, encoding="utf-8"))
            merged = {f.get("page"): f for f in (old.get("frames") or [])}
            for f in doc["frames"]:
                merged[f.get("page")] = f
            doc["frames"] = [merged[k] for k in
                             sorted(merged, key=lambda x: (len(str(x)), str(x)))]
            print("（并入已有 %d 帧，合并后 %d 帧）"
                  % (len(old.get("frames") or []), len(doc["frames"])))
        except Exception as exc:  # noqa: BLE001
            print("（旧文件读不了，按新的写：%s）" % exc)

    json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    empty = [f.get("page") for f in frames
             if not f.get("error") and not f.get("tables") and not f.get("listItems")
             and not any(g["fields"] for g in f.get("groups") or [])]
    print("\n→ %s" % p)
    print("  %d 帧，截图 %d 张" % (len(frames), len([f for f in frames if f.get("shot")])))
    if empty:
        print("\n⚠ 这些帧什么都没抽到：%s" % "、".join(map(str, empty)))
        print("  按下面顺序查，八成是第一条：")
        print("   1. 没登录。launch_chrome.py 起的是全新 profile，里面没有你的登录态。")
        print("      用 %s launch_chrome.py --headed 起浏览器，"
              "在那个窗口里登录一次，再重抓。"
              % _compat.python_cmd())
        print("   2. 页面没加载完（慢网/首屏要选客户）。给 URL 直接带参数。")
        print("   3. 这个页面确实没有表格和表单（纯看板/图），那就说明它本身没有结构可抓。")
        print("  原型帧若拿它们当来源，等于凭印象画。")
        return 5
    print("\n下一步：%s %s --snapshot %s --data modules/<key>.json"
          % (_compat.python_cmd(), os.path.join(HERE, "proto_from_snapshot.py"), p))
    return 0


if __name__ == "__main__":
    _compat.init()   # 控制台编码兜底（Windows 默认 cp936 编不出 ✓ ✗）
    sys.exit(main())
