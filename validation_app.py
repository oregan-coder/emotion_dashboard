# -*- coding: utf-8 -*-
"""
Phase2-03A-R1: 最小只读QA入口
C1: 使用共享snapshot_loader模块，统一路径配置
独立于 dashboard_data/history_manager/backtest_engine 的导入。
只提供 /validation 页面和 /api/validation 只读API。
QA端口：5001（主站web_app.py使用5000）
"""
import sys
from pathlib import Path
from flask import Flask, render_template, jsonify, request

# 确保能导入snapshot_loader（支持从src目录或包根运行）
BASE_DIR = Path(__file__).parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from snapshot_loader import SnapshotConfig, load_validation_data, get_config

# 模板目录：优先用src/templates，兼容包根templates
TEMPLATE_DIR = BASE_DIR / "templates"
if not TEMPLATE_DIR.exists():
    TEMPLATE_DIR = BASE_DIR.parent / "templates"

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))


@app.route('/')
def index():
    """最小入口首页：重定向到validation"""
    return render_template('validation.html')


@app.route('/validation')
def validation_page():
    """数据与验证只读页面"""
    return render_template('validation.html')


@app.route('/api/validation')
def api_validation():
    """数据与验证页面JSON API（Web02.1: 统一错误出口）"""
    requested_date = request.args.get('date')
    config = get_config()
    data, load_status, errors = load_validation_data(config, requested_date)
    if data is None:
        # 加载失败：返回错误结构
        error_map = {
            "FILE_MISSING": (404, "SNAPSHOT_FILE_MISSING"),
            "DATE_NOT_FOUND": (404, "SNAPSHOT_DATE_NOT_FOUND"),
            "JSON_CORRUPTED": (400, "SNAPSHOT_CORRUPTED"),
            "STRUCTURE_INVALID": (400, "SNAPSHOT_STRUCTURE_INVALID"),
            "HASH_MISSING": (400, "SNAPSHOT_HASH_MISSING"),
            "HASH_MISMATCH": (400, "SNAPSHOT_HASH_MISMATCH"),
            "READ_ERROR": (500, "SNAPSHOT_READ_ERROR"),
        }
        status_code, unified_error_type = error_map.get(load_status, (400, "SNAPSHOT_UNKNOWN_ERROR"))
        return jsonify({
            "snapshot_id": "load_error",
            "error_type": unified_error_type,
            "error_message": "; ".join(errors),
            "candidates": [],
            "market_metrics": [],
            "legacy_results": [],
            "shadow_results": [],
        }), status_code
    return jsonify(data), 200


@app.route('/api/validation/config')
def api_config():
    """返回当前配置（调试用）"""
    config = get_config()
    return jsonify({
        "project_root": str(config.project_root),
        "snapshot_path": str(config.snapshot_path),
        "snapshot_exists": config.snapshot_path.exists(),
        "inputs_path": str(config.inputs_path),
        "inputs_exists": config.inputs_path.exists(),
    })


if __name__ == '__main__':
    config = get_config()
    print("=" * 60)
    print("Phase2-03A-R1 最小只读QA入口")
    print("=" * 60)
    print("项目根: %s" % config.project_root)
    print("快照文件: %s" % config.snapshot_path)
    print("快照存在: %s" % config.snapshot_path.exists())
    print("输入目录: %s" % config.inputs_path)
    print("模板目录: %s" % TEMPLATE_DIR)
    print()
    print("访问地址 (QA端口5001):")
    print("  页面: http://127.0.0.1:5001/validation")
    print("  API:  http://127.0.0.1:5001/api/validation")
    print("  配置: http://127.0.0.1:5001/api/validation/config")
    print()
    print("注意: 主站web_app.py使用端口5000，本QA入口使用端口5001")
    print("      127.0.0.1是执行机器本地地址")
    print("      本入口不依赖 dashboard_data/history_manager/backtest_engine")
    print("      不暴露更新/交易接口，只读展示")
    print("=" * 60)

    app.run(
        host='0.0.0.0',
        port=5001,
        debug=False
    )
