"""统计 v4 JSON + 列 backend 源码"""
import json
import os
from collections import Counter

v4 = json.load(open(r'D:\简历帮\AI岗位JD库_v4_intern.json', encoding='utf-8'))
jds = v4['jds']

print("=" * 70)
print("v4 主库统计")
print("=" * 70)
print("总 JD: {} 份".format(len(jds)))
print("版本: {}".format(v4['_meta']['version']))
print("生成日期: {}".format(v4['_meta']['generated_at']))
print("筛选维度: {}".format(v4['_meta']['filter_dimension']))
print()
print("intern_match 分布:")
stats = v4['_meta']['stats']['intern_match']
for k, v in stats.items():
    pct = v / len(jds) * 100
    print("  {:18s} {:3d} 份 ({:.0f}%)".format(k, v, pct))
print()
print("公司分布 (按 JD 数降序):")
co_count = Counter(j['company'] for j in jds)
for co, cnt in sorted(co_count.items(), key=lambda x: -x[1]):
    print("  {:14s} {:2d} 份".format(co, cnt))
print()
print("role_category 分布:")
rc_count = Counter(j['role_category'] for j in jds)
for rc, cnt in sorted(rc_count.items(), key=lambda x: -x[1]):
    print("  {:14s} {:2d} 份".format(rc, cnt))
print()
print("=" * 70)
print("实习可投清单 (strong + campus_to_intern, 共 {} 份)".format(
    stats['strong'] + stats['campus_to_intern']))
print("=" * 70)
intern_ok = [j for j in jds if j.get('intern_match') in ('strong', 'campus_to_intern')]
intern_ok.sort(key=lambda x: (0 if x['intern_match'] == 'strong' else 1, -x['scores']['total']))
for j in intern_ok:
    sig = "🟢" if j['intern_match'] == 'strong' else "🟡"
    print("  {} {:6s} {:14s} {:3d}分 | {}".format(
        sig, j['id'], j['company'], j['scores']['total'], j['title'][:55]))

print()
print("=" * 70)
print("backend/ 源码")
print("=" * 70)
backend_files = []
for root, dirs, files in os.walk(r'D:\简历帮\backend'):
    if any(p in root for p in ('output', 'logs', '__pycache__', '.pytest_cache')):
        continue
    for f in files:
        if f.endswith('.pyc'):
            continue
        full = os.path.join(root, f)
        rel = os.path.relpath(full, r'D:\简历帮')
        size = os.path.getsize(full)
        backend_files.append((rel, size))
backend_files.sort()
for rel, size in backend_files:
    print("  {:60s} {:>7.1f} KB".format(rel, size/1024))

print()
print("=" * 70)
print("frontend/ 源码")
print("=" * 70)
frontend_files = []
for root, dirs, files in os.walk(r'D:\简历帮\frontend'):
    if any(p in root for p in ('node_modules', 'dist', '.git')):
        continue
    for f in files:
        if f.endswith(('.map', '.lock')):
            continue
        full = os.path.join(root, f)
        rel = os.path.relpath(full, r'D:\简历帮')
        size = os.path.getsize(full)
        if size == 0:
            continue
        frontend_files.append((rel, size))
frontend_files.sort()
for rel, size in frontend_files:
    print("  {:60s} {:>7.1f} KB".format(rel, size/1024))

print()
print("=" * 70)
print(".harness/ 团队协作")
print("=" * 70)
harness_files = []
for root, dirs, files in os.walk(r'D:\简历帮\.harness'):
    for f in files:
        full = os.path.join(root, f)
        rel = os.path.relpath(full, r'D:\简历帮')
        size = os.path.getsize(full)
        harness_files.append((rel, size))
harness_files.sort()
for rel, size in harness_files:
    print("  {:60s} {:>7.1f} KB".format(rel, size/1024))