#!/usr/bin/env python3
"""旅費精算書自動生成アプリ"""

import io
import datetime
import random
from flask import Flask, render_template, request, send_file, jsonify

from generate_docx import generate_travel_expense_report
from generate_pdf import generate_travel_expense_pdf
from generate_realestate_export import generate_excel, generate_word, generate_pdf

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/realestate")
def realestate():
    return render_template("realestate.html")


@app.route("/api/realestate/export", methods=["POST"])
def realestate_export():
    data = request.json
    fmt = data.get("format", "excel")
    prop_name = data.get("property", {}).get("name", "物件")

    if fmt == "excel":
        buf = generate_excel(data)
        return send_file(buf, as_attachment=True,
                         download_name=f"不動産CF_{prop_name}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    elif fmt == "word":
        buf = generate_word(data)
        return send_file(buf, as_attachment=True,
                         download_name=f"不動産CF_{prop_name}.docx",
                         mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    elif fmt == "pdf":
        buf = generate_pdf(data)
        return send_file(buf, as_attachment=True,
                         download_name=f"不動産CF_{prop_name}.pdf",
                         mimetype="application/pdf")
    else:
        return jsonify({"error": "Unknown format"}), 400


@app.route("/api/generate-reason", methods=["POST"])
def generate_reason():
    """出張理由をAI的に自動生成する"""
    data = request.json
    purposes = data.get("purposes", [])
    if not purposes:
        purposes = [data.get("purpose", "")]
    destination = data.get("destination", "")
    nights = int(data.get("nights", 1))
    purpose_detail = data.get("purpose_detail", "")

    reason = _generate_trip_reason(purposes, destination, nights, purpose_detail)
    return jsonify({"reason": reason})


@app.route("/api/generate-report-text", methods=["POST"])
def generate_report_text():
    """出張報告をAI的に自動生成する"""
    data = request.json
    purposes = data.get("purposes", [])
    if not purposes:
        purposes = [data.get("purpose", "")]
    destination = data.get("destination", "")
    nights = int(data.get("nights", 1))
    purpose_detail = data.get("purpose_detail", "")

    report = _generate_trip_report(purposes, destination, nights, purpose_detail)
    return jsonify({"report": report})


@app.route("/api/generate-report", methods=["POST"])
def generate_report():
    """出張旅費精算書をWord文書として生成"""
    data = request.json

    company_name = data.get("company_name", "")
    employee_name = data.get("employee_name", "")
    position = data.get("position", "一般社員")
    department = data.get("department", "")
    destination = data.get("destination", "")
    purpose = data.get("purpose", "")
    purpose_detail = data.get("purpose_detail", "")
    start_date = data.get("start_date", "")
    end_date = data.get("end_date", "")
    nights = int(data.get("nights", 1))
    accommodation_fee = int(data.get("accommodation_fee", 20000))
    daily_allowance = int(data.get("daily_allowance", 2000))
    transport_details = data.get("transport_details", [])
    trip_reason = data.get("trip_reason", "")
    trip_report = data.get("trip_report", "")

    purposes = data.get("purposes", [purpose] if purpose else [])

    if not trip_reason:
        trip_reason = _generate_trip_reason(purposes, destination, nights, purpose_detail)

    if not trip_report:
        trip_report = _generate_trip_report(purposes, destination, nights, purpose_detail)

    buf = generate_travel_expense_report(
        company_name=company_name,
        employee_name=employee_name,
        position=position,
        department=department,
        destination=destination,
        purpose=purpose,
        purpose_detail=purpose_detail,
        start_date=start_date,
        end_date=end_date,
        nights=nights,
        accommodation_fee=accommodation_fee,
        daily_allowance=daily_allowance,
        transport_details=transport_details,
        trip_reason=trip_reason,
        trip_report=trip_report,
    )

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"出張旅費精算書_{employee_name}_{start_date}.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.route("/api/generate-report-pdf", methods=["POST"])
def generate_report_pdf():
    """出張旅費精算書をPDF文書として生成"""
    data = request.json

    company_name = data.get("company_name", "")
    employee_name = data.get("employee_name", "")
    position = data.get("position", "一般社員")
    department = data.get("department", "")
    destination = data.get("destination", "")
    purpose = data.get("purpose", "")
    purpose_detail = data.get("purpose_detail", "")
    start_date = data.get("start_date", "")
    end_date = data.get("end_date", "")
    nights = int(data.get("nights", 1))
    accommodation_fee = int(data.get("accommodation_fee", 20000))
    daily_allowance = int(data.get("daily_allowance", 2000))
    transport_details = data.get("transport_details", [])
    trip_reason = data.get("trip_reason", "")
    trip_report = data.get("trip_report", "")

    purposes = data.get("purposes", [purpose] if purpose else [])

    if not trip_reason:
        trip_reason = _generate_trip_reason(purposes, destination, nights, purpose_detail)

    if not trip_report:
        trip_report = _generate_trip_report(purposes, destination, nights, purpose_detail)

    buf = generate_travel_expense_pdf(
        company_name=company_name,
        employee_name=employee_name,
        position=position,
        department=department,
        destination=destination,
        purpose=purpose,
        purpose_detail=purpose_detail,
        start_date=start_date,
        end_date=end_date,
        nights=nights,
        accommodation_fee=accommodation_fee,
        daily_allowance=daily_allowance,
        transport_details=transport_details,
        trip_reason=trip_reason,
        trip_report=trip_report,
    )

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"出張旅費精算書_{employee_name}_{start_date}.pdf",
        mimetype="application/pdf",
    )


def _generate_trip_reason(purposes: list, destination: str, nights: int, purpose_detail: str = "") -> str:
    """出張理由を自動生成（複数目的対応・詳細反映）"""
    reason_snippets = {
        "不動産会社周り": [
            "不動産物件の現地調査および不動産会社との打ち合わせ",
            "投資用不動産の視察および不動産仲介業者との商談",
            "新規不動産案件に関する現地調査および関係各社との協議",
        ],
        "クライアント相談": [
            "主要クライアントとの業務打ち合わせおよび案件進捗の確認",
            "クライアント企業訪問によるプロジェクト協議および事業展開の相談",
            "クライアントとの契約内容見直しおよび今後の取引方針協議",
        ],
        "コンサル案件": [
            "コンサルティング案件の現地調査およびクライアント企業との戦略会議",
            "コンサルティングプロジェクト推進のための現場視察および経営陣との戦略ミーティング",
        ],
        "セミナー・研修": [
            "業界セミナーへの参加および関連企業とのネットワーキング",
            "専門研修プログラムへの参加によるスキル向上および最新知識の習得",
        ],
        "新規営業": [
            "新規取引先の開拓営業（見込み顧客への訪問・サービス提案・条件交渉）",
            "新規市場開拓を目的とした営業活動および市場ニーズ調査",
        ],
        "現場視察": [
            "事業現場の視察および進捗確認・品質管理体制の確認",
            "現場状況の実地確認および業務改善に向けた課題抽出・対策検討",
        ],
        "契約締結・交渉": [
            "取引先との契約交渉および締結手続き（条件確認・合意事項の調整・署名）",
            "取引先企業との契約条件の精査・折衝および合意形成",
        ],
    }

    detail_parts = []
    for p in purposes:
        snippets = reason_snippets.get(p, [f"{p}に関する業務遂行"])
        detail_parts.append(random.choice(snippets))

    purpose_text = "、".join(detail_parts)

    # 詳細が入力されている場合、具体的な内容を文章に組み込む
    detail_sentence = ""
    if purpose_detail and purpose_detail.strip():
        detail_sentence = f"\n具体的には、{purpose_detail.strip()}を予定しており、現地での直接対応が不可欠である。"

    templates = [
        f"{destination}において、{purpose_text}を行うため。{detail_sentence}"
        f"現地での対面による打ち合わせ・調査が不可欠であり、"
        f"効率的な業務遂行のため{nights}泊の出張を要する。",

        f"{destination}にて、{purpose_text}を実施するため。{detail_sentence}"
        f"リモートでは対応困難な現地確認事項があり、"
        f"所期の目的を達成するために{nights}泊の日程で出張を行う必要がある。",

        f"{destination}への出張目的は以下のとおりである。"
        f"{purpose_text}。{detail_sentence}"
        f"上記業務はいずれも現地での対面実施が必要であり、{nights}泊の日程とする。",
    ]

    return random.choice(templates)


def _generate_trip_report(purposes: list, destination: str, nights: int, purpose_detail: str = "") -> str:
    """出張報告内容を自動生成（複数目的対応・詳細反映）"""
    report_snippets = {
        "不動産会社周り": [
            "不動産会社を訪問し、物件情報の収集および現地視察を実施した。"
            "複数の候補物件について立地条件・築年数・設備状況等を確認し、投資判断に必要な情報を取得した。",
        ],
        "クライアント相談": [
            "クライアント企業を訪問し、業務打ち合わせを実施した。"
            "案件の進捗確認、スケジュール調整、および新たな要望事項のヒアリングを行った。",
        ],
        "コンサル案件": [
            "コンサルティング先企業を訪問し、現地調査および戦略会議を実施した。"
            "経営課題の現状を確認し、改善施策の方向性について合意を得た。",
        ],
        "セミナー・研修": [
            "セミナー・研修に参加し、最新の業界動向および専門知識の習得を行った。"
            "得られた知見は社内で共有し、今後の業務改善に活用する予定である。",
        ],
        "新規営業": [
            "見込み顧客を訪問し、新規営業活動を実施した。"
            "当社サービスの説明・提案を行い、複数の企業から前向きな反応を得た。",
        ],
        "現場視察": [
            "事業現場を視察し、運営状況の確認および課題の抽出を行った。"
            "現場スタッフとの意見交換を通じて改善点を整理した。",
        ],
        "契約締結・交渉": [
            "取引先との契約交渉を実施し、主要条件について合意に達した。"
            "契約書の最終確認を行い、署名手続きを完了した。",
        ],
    }

    parts = []
    for p in purposes:
        snippets = report_snippets.get(p, [f"{p}に関する業務を遂行した。"])
        parts.append(random.choice(snippets))

    report_body = "\n".join(
        f"{i+1}. {part}" if len(parts) > 1 else part
        for i, part in enumerate(parts)
    )

    # 詳細が入力されている場合、具体的な活動内容として報告に組み込む
    detail_section = ""
    if purpose_detail and purpose_detail.strip():
        detail_section = f"\n\n【活動詳細】\n{purpose_detail.strip()}について対応を行い、所期の成果を得ることができた。"

    closing = "今後、上記の成果を踏まえ、社内検討・フォローアップを速やかに進める予定である。"

    if len(parts) > 1:
        return f"{destination}にて以下の業務を遂行した。\n{report_body}{detail_section}\n{closing}"
    else:
        return f"{destination}にて{report_body}{detail_section}\n{closing}"


def find_free_port():
    """空いているポートを自動で見つける"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def get_resource_path(relative_path):
    """PyInstaller でバンドルされた場合のリソースパスを取得"""
    import sys, os
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)


if __name__ == "__main__":
    import os, sys, threading, webbrowser

    # PyInstaller バンドル時のテンプレートパス設定
    if getattr(sys, "frozen", False):
        app.template_folder = get_resource_path("templates")

    port = int(os.environ.get("PORT", 0))
    if port == 0:
        port = find_free_port()

    # デバッグモード判定（バンドル時はOFF）
    is_debug = not getattr(sys, "frozen", False)

    def open_browser():
        webbrowser.open(f"http://localhost:{port}")

    if not is_debug:
        # バンドル版: 1秒後にブラウザを自動で開く
        threading.Timer(1.0, open_browser).start()
        print(f"旅費精算アプリを起動中... http://localhost:{port}")
        print("ブラウザが自動で開きます。閉じるにはこのウィンドウを閉じてください。")

    app.run(debug=is_debug, port=port, use_reloader=False)
