import io
import socket
import struct
import zlib
from enum import Enum
from typing import Any
from pprint import pprint
import datetime

from binary_reader import BinaryReader


class Api:
    class Market(Enum):
        SZ = 0
        SH = 1

    class KLineCategory(Enum):
        K5 = 0
        K15 = 1
        K30 = 2
        K60 = 3
        KDaily = 4
        KWeek = 5
        KMonth = 6
        PerMinute = 7
        K1 = 8
        KDay = 9
        KSeason = 10
        KYear = 11

    _client: socket.socket

    RSP_HEADER_LENGTH = 0x10

    def __init__(self, host: str = '119.147.212.81', port: int = 7709) -> None:
        self._client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._client.connect((host, port))
        self._hello()

    def _hello(self) -> None:
        self._req(b'\x0c\x02\x18\x93\x00\x01\x03\x00\x03\x00\x0d\x00\x01')
        self._req(b'\x0c\x02\x18\x94\x00\x01\x03\x00\x03\x00\x0d\x00\x02')
        self._req(b'\x0c\x03\x18\x99\x00\x01\x20\x00\x20\x00\xdb\x0f\xd5'
                  b'\xd0\xc9\xcc\xd6\xa4\xa8\xaf\x00\x00\x00\x8f\xc2\x25'
                  b'\x40\x13\x00\x00\xd5\x00\xc9\xcc\xbd\xf0\xd7\xea\x00'
                  b'\x00\x00\x02')

    def get_stocks_count(self, market: Market) -> int:
        reader = self._req(
            b'\x0c\x0c\x18\x6c\x00\x01\x08\x00\x08\x00\x4e\x04' + bytes([market.value]) + b'\x00\x75\xc7\x33\x01')
        return reader.u16

    def get_stocks_list(self, market: Market, start: int) -> list[dict[str, Any]]:
        package = b'\x0c\x01\x18\x64\x01\x01\x06\x00\x06\x00\x50\x04' + struct.pack('<HH', market.value, start)
        reader = self._req(package)
        stocks_count = reader.u16
        stocks = []
        for _ in range(stocks_count):
            stocks.append({
                '股票代码': reader.read(6).decode(),
                'volunit': reader.u16,
                '股票名称': reader.read(8).decode('gbk').rstrip('\x00'),
                'reserved_bytes1': reader.read(4),
                'decimal_point': reader.u8,
                '昨日收盘价': reader.f32,
                'reserved_bytes2': reader.read(4)
            })
        return stocks

    def get_stock_quotes(self, stocks: list[tuple[Market, str]]) -> list[dict[str, Any]]:
        stocks_count = len(stocks)
        package_size = stocks_count * 7 + 12
        package = bytearray(struct.pack('<HIHHIIHH', 0x10c, 0x02006320,
                                        package_size, package_size,
                                        0x5053e, 0, 0,
                                        stocks_count))
        for market, stock in stocks:
            package.extend(struct.pack('<B6s', market.value, stock.encode()))
        reader = self._req(package)
        reader.skip(2)
        stocks_count = reader.u16
        stocks = []

        for _ in range(stocks_count):
            market, stock, active1 = struct.unpack('<B6sH', reader.read(9))
            price = reader.vint
            stocks.append({
                '市场': self.Market(market),
                '股票代码': stock,
                'active1': active1,
                '股价': self._calc_price(price, 0),
                '昨日收盘价': self._calc_price(price, reader.vint),
                '今日开盘价': self._calc_price(price, reader.vint),
                '最高价': self._calc_price(price, reader.vint),
                '最低价': self._calc_price(price, reader.vint),
                '服务器时间': self._format_time(reader.vint),
                'reserved_bytes1': reader.vint,
                '成交量': reader.vint,
                '当前成交量': reader.vint,
                '成交额': reader.f32,
                '内盘': reader.vint,
                '外盘': reader.vint,
                'reserved_bytes2': reader.vint,
                'reserved_bytes3': reader.vint,
                '买1': self._calc_price(price, reader.vint),
                '卖1': self._calc_price(price, reader.vint),
                '买1成交量': reader.vint,
                '卖1成交量': reader.vint,
                '买2': self._calc_price(price, reader.vint),
                '卖2': self._calc_price(price, reader.vint),
                '买2成交量': reader.vint,
                '卖2成交量': reader.vint,
                '买3': self._calc_price(price, reader.vint),
                '卖3': self._calc_price(price, reader.vint),
                '买3成交量': reader.vint,
                '卖3成交量': reader.vint,
                '买4': self._calc_price(price, reader.vint),
                '卖4': self._calc_price(price, reader.vint),
                '买4成交量': reader.vint,
                '卖4成交量': reader.vint,
                '买5': self._calc_price(price, reader.vint),
                '卖5': self._calc_price(price, reader.vint),
                '买5成交量': reader.vint,
                '卖5成交量': reader.vint,
                'reserved_bytes4': reader.u16,
                'reserved_bytes5': reader.vint,
                'reserved_bytes6': reader.vint,
                'reserved_bytes7': reader.vint,
                'reserved_bytes8': reader.vint,
                '增速': reader.i16 / 100,
                'active2': reader.u16
            })
        return stocks

    def get_k_line(self, category: KLineCategory, market: Market, stock: str, start: int, count: int) -> list[
            dict[str, Any]]:
        reader = self._req(struct.pack('<HIHHHH6sHHHHIIH',
                                       0x10c, 0x01016408, 0x1c, 0x1c, 0x052d,
                                       market.value,
                                       stock.encode(),
                                       category.value,
                                       1,
                                       start, count,
                                       0, 0, 0))
        try:  # 指数
            count = reader.u16
            klines = []
            pre_diff_base = 0
            for _ in range(count):
                date = self._get_datetime(category, reader)
                price_open_diff = reader.vint
                price_close_diff = reader.vint
                price_high_diff = reader.vint
                price_low_diff = reader.vint
                price_open = self._calc_price1k(price_open_diff, pre_diff_base)
                price_open_diff += pre_diff_base

                pre_diff_base = price_open_diff + price_close_diff
                klines.append({
                    '时刻': date,
                    '开盘价': price_open,
                    '收盘价': self._calc_price1k(price_open_diff, price_close_diff),
                    '最高价': self._calc_price1k(price_open_diff, price_high_diff),
                    '最低价': self._calc_price1k(price_open_diff, price_low_diff),
                    '成交量': reader.f32,
                    '成交额': reader.f32,
                    '上涨数': reader.u16,
                    '下跌数': reader.u16
                })
            return klines
        except ValueError:  # 不是指数
            reader.pos = 0
            count = reader.u16
            klines = []
            pre_diff_base = 0
            for _ in range(count):
                date = self._get_datetime(category, reader)
                price_open_diff = reader.vint
                price_close_diff = reader.vint
                price_high_diff = reader.vint
                price_low_diff = reader.vint
                price_open = self._calc_price1k(price_open_diff, pre_diff_base)
                price_open_diff += pre_diff_base

                pre_diff_base = price_open_diff + price_close_diff
                klines.append({
                    '时刻': date,
                    '开盘价': price_open,
                    '收盘价': self._calc_price1k(price_open_diff, price_close_diff),
                    '最高价': self._calc_price1k(price_open_diff, price_high_diff),
                    '最低价': self._calc_price1k(price_open_diff, price_low_diff),
                    '成交量': reader.f32,
                    '成交额': reader.f32,
                })
            return klines

    def get_minute_data(self, market: Market, stock: str) -> list[dict[str, Any]]:
        reader = self._req(
            b'\x0c\x1b\x08\x00\x01\x01\x0e\x00\x0e\x00\x1d\x05' + struct.pack('<H6sI', market.value, stock.encode(), 0))
        count = reader.u16
        last_price = 0
        reader.skip(2)
        prices = []
        for _ in range(count):
            price_raw = reader.vint
            _reserved1 = reader.vint
            last_price += price_raw
            prices.append({
                '价格': last_price / 100,
                '成交量': reader.vint
            })
        return prices

    def get_history_minute_data(self, market: Market, stock: str, date: int) -> list[dict[str, Any]]:
        reader = self._req(
            b'\x0c\x01\x30\x00\x01\x01\x0d\x00\x0d\x00\xb4\x0f' + struct.pack('<IB6s', date, market.value,
                                                                              stock.encode()))
        count = reader.u16
        last_price = 0
        reader.skip(4)
        prices = []
        for _ in range(count):
            price_raw = reader.vint
            _reserved1 = reader.vint
            last_price += price_raw
            prices.append({
                '价格': last_price / 100,
                '成交量': reader.vint
            })
        return prices

    def get_transaction_data(self, market: Market, stock: str, start: int, count: int) -> list[dict[str, Any]]:
        reader = self._req(
            b'\x0c\x17\x08\x01\x01\x01\x0e\x00\x0e\x00\xc5\x0f' + struct.pack('<H6sHH', market.value, stock.encode(),
                                                                              start, count))
        count = reader.u16
        last_price = 0
        trades = []
        for _ in range(count):
            time = self._get_time(reader)
            last_price += reader.vint

            trades.append({
                '时间': time,
                '价格': last_price / 100,
                '成交量': reader.vint,
                'num': reader.vint,
                'buyorsell': reader.vint
            })
            _reserved1 = reader.vint
        return trades

    def get_history_transaction_data(self, market: Market, stock: str, start: int, count: int, date: int) -> list[
        dict[str, Any]]:
        reader = self._req(
            b'\x0c\x01\x30\x01\x00\x01\x12\x00\x12\x00\xb5\x0f' + struct.pack('<IH6sHH', date, market.value,
                                                                              stock.encode(), start, count))
        trades = []
        count = reader.u16
        reader.skip(4)
        last_price = 0
        for _ in range(count):
            time = self._get_time(reader)
            last_price += reader.vint

            trades.append({
                '时间': time,
                '价格': last_price / 100,
                '成交量': reader.vint,
                'num': reader.vint,
                'buyorsell': reader.vint
            })
        return trades

    def get_company_info_entry(self, market: Market, stock: str) -> list[dict[str, Any]]:
        reader = self._req(
            b'\x0c\x0f\x10\x9b\x00\x01\x0e\x00\x0e\x00\xcf\x02' + struct.pack('<H6sI', market.value, stock.encode(), 0))
        count = reader.u16

        entries = []
        for _ in range(count):
            entries.append({
                '名称': reader.rpad_str(64),
                '文件名': reader.rpad_str(80),
                '起始': reader.u32,
                '长度': reader.u32
            })
        return entries

    def get_company_info_content(self, market: Market, stock: str, filename: str, start: int, length: int) -> str:
        reader = self._req(b'\x0c\x07\x10\x9c\x00\x01\x68\x00\x68\x00\xd0\x02' + struct.pack('<H6sH80sIII',
                                                                                             market.value,
                                                                                             stock.encode(),
                                                                                             0,
                                                                                             filename.encode().ljust(80,
                                                                                                                     b'\0'),
                                                                                             start, length, 0))
        _ = reader.read(10)
        length = reader.u16
        return reader.read(length).decode('gbk')

    def get_finance_info(self, market: Market, stock: str):
        reader = self._req(
            b'\x0c\x1f\x18\x76\x00\x01\x0b\x00\x0b\x00\x10\x00\x01\x00' + struct.pack('<B6s', market.value,
                                                                                      stock.encode()))
        reader.skip(2)
        return {
            '市场': self.Market(reader.u8),
            '股票代码': reader.read(6).decode(),
            '流动股本': reader.f32 * 10000,
            '省': reader.u16,
            '工业': reader.u16,
            '更新日期': reader.u32,
            'ipo_date': reader.u32,
            '总股本': reader.f32 * 10000,
            '国家股': reader.f32 * 10000,
            '发起人法人股': reader.f32 * 10000,
            '法人股': reader.f32 * 10000,
            'B股': reader.f32 * 10000,
            'H股': reader.f32 * 10000,
            '职工股': reader.f32 * 10000,
            '总资产': reader.f32 * 10000,
            '流动资产': reader.f32 * 10000,
            '固定资产': reader.f32 * 10000,
            '无形资产': reader.f32 * 10000,
            '股东人数': reader.f32 * 10000,
            '流动负债': reader.f32 * 10000,
            '长期负债': reader.f32 * 10000,
            '资本公积金': reader.f32 * 10000,
            '净资产': reader.f32 * 10000,
            '主营收入': reader.f32 * 10000,
            '主营利润': reader.f32 * 10000,
            '营收账款': reader.f32 * 10000,
            '营业利润': reader.f32 * 10000,
            '投资收入': reader.f32 * 10000,
            '经营现金流': reader.f32 * 10000,
            '总现金流': reader.f32 * 10000,
            '存活': reader.f32 * 10000,
            '利润总和': reader.f32 * 10000,
            '税后利润': reader.f32 * 10000,
            '净利润': reader.f32 * 10000,
            '未分配利润': reader.f32 * 10000,
            '每股净资产': reader.f32,
            'reserved2': reader.f32
        }

    def _format_time(self, timestamp: int) -> str:
        timestamp = str(timestamp)
        time = timestamp[:-6] + ':'
        if int(timestamp[-6:-4]) < 60:
            time += f'{timestamp[-6:-4]}:{int(timestamp[-4:] * 60) / 10000:06.3f}'
        else:
            time += f'{int(int(timestamp[-6:]) * 60 / 1000000):02d}:{(int(timestamp[-6:]) * 60 % 1000000) * 60 / 1000000:06.3f}'
        return time

    def _get_datetime(self, category: KLineCategory, reader: BinaryReader) -> datetime.datetime:
        if category.value < self.KLineCategory.KDaily.value or category in (
                self.KLineCategory.PerMinute, self.KLineCategory.K1):
            zipday = reader.u16
            tminutes = reader.u16
            return datetime.datetime((zipday >> 11) + 2004,
                                     int((zipday % 2048) / 100),
                                     (zipday % 2048) % 100,
                                     int(tminutes / 60),
                                     tminutes % 60)
        else:
            zipday = reader.u32
            return datetime.datetime(zipday // 10000,
                                     (zipday % 10000) // 100,
                                     zipday % 100,
                                     15)

    def _get_time(self, reader: BinaryReader) -> datetime.time:
        tminutes = reader.u16
        return datetime.time(tminutes // 60, tminutes % 60)

    def _calc_price(self, base_value: float, offset: float) -> float:
        return (base_value + offset) / 100

    def _calc_price1k(self, base_value: float, offset: float) -> float:
        return (base_value + offset) / 1000

    def _req(self, data: bytes) -> BinaryReader:
        self._client.send(data)
        return BinaryReader(io.BytesIO(self._recv()))

    def _send(self, data: bytes) -> int:
        return self._client.send(data)

    def _recv(self) -> bytes:
        recv = self._client.recv(self.RSP_HEADER_LENGTH)
        _r1, _r2, _r3, zipped_size, unzipped_size = struct.unpack('<IIIHH', recv)
        data = bytes()
        remained_size = zipped_size
        while remained_size > 0:
            data += self._client.recv(remained_size)
            remained_size -= len(data)
        if zipped_size != unzipped_size:
            data = zlib.decompress(data)
        return data

    def __enter__(self) -> 'Api':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


if __name__ == '__main__':
    with Api() as api:
        pprint(api.get_finance_info(Api.Market.SZ, '002532'))