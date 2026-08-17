#!/usr/bin/env python3
"""Web server for waybill printing."""
import json
import subprocess
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import tempfile
import os
from email.parser import BytesParser

from database import save_waybill, get_recent_waybills, get_waybill
from printer import print_waybill, list_printers
from excel_import import parse_excel, generate_template

PORT = 8899
HTML_FILE = Path(__file__).parent / "index.html"


class WaybillHandler(SimpleHTTPRequestHandler):
    """Handle HTTP requests."""
    
    def do_GET(self):
        """Handle GET requests."""
        path = urlparse(self.path).path

        if path == '/' or path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            with open(HTML_FILE, 'r', encoding='utf-8') as f:
                self.wfile.write(f.read().encode('utf-8'))
        elif path == '/api/printers':
            printers = list_printers()
            self.send_json({'printers': printers})
        elif path == '/api/history':
            waybills = get_recent_waybills()
            self.send_json({'waybills': waybills})
        elif path.startswith('/api/waybill/'):
            waybill_id = int(path.split('/')[-1])
            waybill = get_waybill(waybill_id)
            self.send_json({'waybill': waybill})
        elif path == '/api/download-template':
            # Download Excel template
            from urllib.parse import quote
            template_data = generate_template()
            filename = quote('运输单模板.xlsx')
            self.send_response(200)
            self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            self.send_header('Content-Disposition', f'attachment; filename*=UTF-8\'\'{filename}')
            self.end_headers()
            self.wfile.write(template_data)
        else:
            self.send_error(404)
    
    def do_POST(self):
        """Handle POST requests."""
        path = urlparse(self.path).path
        content_length = int(self.headers.get('Content-Length', 0))
        content_type = self.headers.get('Content-Type', '')

        # 文件上传需要二进制读取
        if path == '/api/import':
            body = self.rfile.read(content_length)
        else:
            body = self.rfile.read(content_length).decode('utf-8')

        try:
            data = json.loads(body) if body and path != '/api/import' else {}
        except json.JSONDecodeError:
            self.send_json({'success': False, 'error': '无效的 JSON 数据'})
            return

        if path == '/api/print':
            # Save and print
            waybill_id = save_waybill(data)
            printer = data.get('printer')
            copies = data.get('copies', 1)

            if printer:
                success = print_waybill(data, printer_name=printer, copies=copies)
                if success:
                    self.send_json({'success': True, 'id': waybill_id})
                else:
                    self.send_json({'success': False, 'error': '打印失败'})
            else:
                self.send_json({'success': False, 'error': '未选择打印机'})

        elif path.startswith('/api/print/'):
            # Print from history
            waybill_id = int(path.split('/')[-1])
            waybill = get_waybill(waybill_id)

            if not waybill:
                self.send_json({'success': False, 'error': '记录不存在'})
                return

            printer = data.get('printer')
            copies = data.get('copies', 1)

            if printer:
                success = print_waybill(waybill, printer_name=printer, copies=copies)
                if success:
                    self.send_json({'success': True})
                else:
                    self.send_json({'success': False, 'error': '打印失败'})
            else:
                self.send_json({'success': False, 'error': '未选择打印机'})

        elif path == '/api/batch-print':
            # Batch print
            waybills = data.get('waybills', [])
            printer = data.get('printer')
            copies = data.get('copies', 1)

            if not printer:
                self.send_json({'success': False, 'error': '未选择打印机'})
                return

            results = []
            for wb in waybills:
                waybill_id = save_waybill(wb)
                success = print_waybill(wb, printer_name=printer, copies=copies)
                results.append({'id': waybill_id, 'success': success})

            success_count = sum(1 for r in results if r['success'])
            self.send_json({
                'success': True,
                'total': len(results),
                'success_count': success_count,
                'results': results
            })

        elif path == '/api/import':
            # Import Excel file
            if 'multipart/form-data' not in content_type:
                self.send_json({'success': False, 'error': '无效的文件格式'})
                return

            # Parse multipart using email.parser
            from email.parser import BytesParser
            from email.policy import default
            
            # Construct a valid email-like message
            boundary = content_type.split('boundary=')[1] if 'boundary=' in content_type else None
            if not boundary:
                self.send_json({'success': False, 'error': '无效的边界'})
                return
            
            msg_bytes = b'Content-Type: multipart/form-data; boundary=' + boundary.encode() + b'\r\n\r\n' + body
            
            try:
                parser = BytesParser(policy=default)
                msg = parser.parsebytes(msg_bytes)
                
                file_content = None
                for part in msg.iter_parts():
                    if part.get_filename():
                        file_content = part.get_payload(decode=True)
                        break
                
                if not file_content:
                    self.send_json({'success': False, 'error': '未找到文件'})
                    return
                
                waybills = parse_excel(file_content)
                self.send_json({
                    'success': True,
                    'count': len(waybills),
                    'waybills': waybills
                })
            except Exception as e:
                self.send_json({'success': False, 'error': f'解析失败：{str(e)}'})

        else:
            self.send_error(404)
    
    def send_json(self, data):
        """Send JSON response."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def main():
    """Start the web server."""
    server = HTTPServer(('localhost', PORT), WaybillHandler)
    print(f"✅ 服务已启动：http://localhost:{PORT}")
    print("按 Ctrl+C 停止服务")
    
    # Open browser
    webbrowser.open(f'http://localhost:{PORT}')
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()


if __name__ == '__main__':
    main()
