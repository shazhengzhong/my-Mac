"""Excel template import for batch waybill printing."""
import json
from openpyxl import load_workbook
from io import BytesIO


# Excel 列映射（列字母 -> 字段名）
COLUMN_MAP = {
    'A': 'departure_station',
    'B': 'arrival_station',
    'C': 'date',
    'D': 'shipper',
    'E': 'shipper_address',
    'F': 'shipper_phone',
    'G': 'receiver',
    'H': 'receiver_address',
    'I': 'contact',
    'J': 'cargo_name_1',
    'K': 'cargo_package_1',
    'L': 'cargo_quantity_1',
    'M': 'cargo_weight_1',
    'N': 'cargo_freight_1',
    'O': 'cargo_pickup_1',
    'P': 'cargo_delivery_1',
    'Q': 'cargo_insurance_value_1',
    'R': 'cargo_insurance_fee_1',
    'S': 'cargo_name_2',
    'T': 'cargo_package_2',
    'U': 'cargo_quantity_2',
    'V': 'cargo_weight_2',
    'W': 'cargo_freight_2',
    'X': 'cargo_pickup_2',
    'Y': 'cargo_delivery_2',
    'Z': 'cargo_insurance_value_2',
    'AA': 'cargo_insurance_fee_2',
    'AB': 'payment_method',
    'AC': 'remarks',
}


def number_to_chinese(num):
    """Convert number to Chinese uppercase."""
    if not num or num == 0:
        return ''
    
    digits = ['零', '壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖']
    units = ['', '拾', '佰', '仟']
    big_units = ['', '万', '亿']
    
    num = abs(float(num))
    int_part = int(num)
    dec_part = round((num - int_part) * 100)
    
    result = ''
    zero_flag = False
    
    int_str = str(int_part)
    for i, digit in enumerate(int_str):
        d = int(digit)
        pos = len(int_str) - 1 - i
        if d == 0:
            zero_flag = True
        else:
            if zero_flag:
                result += '零'
                zero_flag = False
            result += digits[d] + units[pos % 4]
            if pos % 4 == 0 and big_units[pos // 4]:
                result += big_units[pos // 4]
    
    if not result:
        result = '零'
    
    if dec_part == 0:
        result += '元整'
    else:
        result += '元'
        if dec_part >= 10:
            result += digits[dec_part // 10] + '角'
        if dec_part % 10 > 0:
            result += digits[dec_part % 10] + '分'
    
    return result


def parse_excel(file_content):
    """Parse Excel file and return waybill list."""
    wb = load_workbook(filename=BytesIO(file_content), read_only=True)
    ws = wb.active
    
    waybills = []
    waybill_counter = 1  # 运单号计数器
    
    # 从第二行开始读取（第一行是表头）
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(row):  # 跳过空行
            continue
        
        # 构建运单数据
        data = {}
        
        # 基本字段
        for col_idx, value in enumerate(row):
            col_letter = chr(65 + col_idx) if col_idx < 26 else chr(64 + col_idx // 26) + chr(65 + col_idx % 26)
            if col_letter in COLUMN_MAP and value is not None:
                field = COLUMN_MAP[col_letter]
                val = str(value).strip() if value else ''
                # 日期格式处理：去掉时间部分
                if field == 'date' and ' ' in val:
                    val = val.split(' ')[0]
                data[field] = val
        
        # 构建货物数据
        cargo_data = []
        
        # 第一行货物
        cargo1 = {
            'name': data.get('cargo_name_1', ''),
            'package': data.get('cargo_package_1', ''),
            'quantity': data.get('cargo_quantity_1', ''),
            'weight_volume': data.get('cargo_weight_1', ''),
            'freight': data.get('cargo_freight_1', ''),
            'pickup_fee': data.get('cargo_pickup_1', ''),
            'delivery_fee': data.get('cargo_delivery_1', ''),
            'insurance_value': data.get('cargo_insurance_value_1', ''),
            'insurance_fee': data.get('cargo_insurance_fee_1', ''),
        }
        
        # 计算合计 1（只有填了数据才计算）
        has_data_1 = any(cargo1.get(k) for k in ['freight', 'pickup_fee', 'delivery_fee', 'insurance_fee'])
        if has_data_1:
            try:
                freight1 = float(cargo1['freight'] or 0)
                pickup1 = float(cargo1['pickup_fee'] or 0)
                delivery1 = float(cargo1['delivery_fee'] or 0)
                insurance_fee1 = float(cargo1['insurance_fee'] or 0)
                cargo1['total'] = str(freight1 + pickup1 + delivery1 + insurance_fee1)
            except:
                cargo1['total'] = ''
        else:
            cargo1['total'] = ''
        
        if any(cargo1.values()):
            cargo_data.append(cargo1)
        
        # 第二行货物
        cargo2 = {
            'name': data.get('cargo_name_2', ''),
            'package': data.get('cargo_package_2', ''),
            'quantity': data.get('cargo_quantity_2', ''),
            'weight_volume': data.get('cargo_weight_2', ''),
            'freight': data.get('cargo_freight_2', ''),
            'pickup_fee': data.get('cargo_pickup_2', ''),
            'delivery_fee': data.get('cargo_delivery_2', ''),
            'insurance_value': data.get('cargo_insurance_value_2', ''),
            'insurance_fee': data.get('cargo_insurance_fee_2', ''),
        }
        
        # 计算合计 2（只有填了数据才计算）
        has_data_2 = any(cargo2.get(k) for k in ['freight', 'pickup_fee', 'delivery_fee', 'insurance_fee'])
        if has_data_2:
            try:
                freight2 = float(cargo2['freight'] or 0)
                pickup2 = float(cargo2['pickup_fee'] or 0)
                delivery2 = float(cargo2['delivery_fee'] or 0)
                insurance_fee2 = float(cargo2['insurance_fee'] or 0)
                cargo2['total'] = str(freight2 + pickup2 + delivery2 + insurance_fee2)
            except:
                cargo2['total'] = ''
        else:
            cargo2['total'] = ''
        
        if any(cargo2.values()):
            cargo_data.append(cargo2)
        
        # 计算总运费
        total_freight = 0
        for cargo in cargo_data:
            try:
                total_freight += float(cargo.get('total', 0) or 0)
            except:
                pass
        
        # 构建最终运单数据
        waybill = {
            'waybill_no': f'{waybill_counter:07d}',  # 自动编号
            'departure_station': data.get('departure_station', ''),
            'arrival_station': data.get('arrival_station', ''),
            'date': data.get('date', ''),
            'shipper': data.get('shipper', ''),
            'shipper_address': data.get('shipper_address', ''),
            'shipper_phone': data.get('shipper_phone', ''),
            'receiver': data.get('receiver', ''),
            'receiver_address': data.get('receiver_address', ''),
            'contact': data.get('contact', ''),
            'cargo_data': json.dumps(cargo_data, ensure_ascii=False),
            'total_freight_words': number_to_chinese(total_freight),
            'total_freight_digits': str(total_freight) if total_freight > 0 else '',
            'payment_method': data.get('payment_method', ''),
            'remarks': data.get('remarks', ''),
        }
        
        waybill_counter += 1  # 递增编号
        
        # 至少需要一个字段
        if any(v for v in waybill.values() if v):
            waybills.append(waybill)
    
    wb.close()
    return waybills


def generate_template():
    """Generate Excel template file."""
    from openpyxl import Workbook
    
    wb = Workbook()
    ws = wb.active
    ws.title = "运输单模板"
    
    # 表头
    headers = [
        '始发站', '到达站', '日期', '托运单位', '托运单位地址', '托运单位电话',
        '收货单位', '收货单位地址', '联系人/电话',
        '货物名称 1', '包装 1', '数量 1', '重量/体积 1', '运费 1', '提货费 1', '送货费 1', '货物保价 1', '保险费 1',
        '货物名称 2', '包装 2', '数量 2', '重量/体积 2', '运费 2', '提货费 2', '送货费 2', '货物保价 2', '保险费 2',
        '付款方式', '备注'
    ]
    
    for col, header in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=header)
    
    # 示例数据
    example = [
        '常熟', '北京', '2026-08-22', '上海某某贸易有限公司', '上海市浦东新区张江路 100 号', '021-12345678',
        '常熟市中伟物流有限公司', '江苏省常熟市某某路 88 号', '张三 13800138000',
        '电子产品', '纸箱', '50', '500kg', '1200', '100', '150', '50000', '200',
        '配件', '木箱', '10', '200kg', '500', '50', '80', '20000', '100',
        '月结', '轻拿轻放'
    ]
    
    for col, value in enumerate(example, start=1):
        ws.cell(row=2, column=col, value=value)
    
    # 调整列宽
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[chr(64 + col) if col <= 26 else 'A' + chr(64 + col - 26)].width = 12
    
    # 保存到内存
    output = BytesIO()
    wb.save(output)
    wb.close()
    return output.getvalue()
