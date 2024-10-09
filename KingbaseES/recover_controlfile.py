#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
脚本作者：Lucifer
创建日期：2024年10月09日
用途：KingbaseES 一键恢复控制文件
"""

import os
import glob
import re
import sys
import subprocess
import argparse

# 1-Oracle, 2-PostgreSQL
compatible_style = 1

# 正则表达式匹配十六进制文件名
hex_pattern = re.compile(r'^[0-9A-Fa-f]+$')


def parse_arguments():
    parser = argparse.ArgumentParser(description="KingbaseES 一键恢复控制文件")
    parser.add_argument("-cs", "--compatible_style", type=int,
                        choices=[1, 2], default=1, help="兼容样式: 1-Oracle, 2-PostgreSQL（可选，默认为 1）")
    parser.add_argument("-kd", "--kingbase_data", type=str,
                        help="KINGBASE_DATA 参数（可选）")

    return parser.parse_args()


def error_message(msg):
    print(f"\n\033[31m{msg}\033[0m\n")


def print_log_info(title, info):
    print(f"\n{'=' * 50}")
    print(f"{title}:")
    print(info)
    print(f"{'=' * 50}\n")


def get_max_hex_number(directory):
    log_files = [
        os.path.basename(f) for f in glob.glob(os.path.join(directory, "*"))
        if hex_pattern.match(os.path.basename(f))
    ]

    if not log_files:
        error_message(f"在目录 '{directory}' 中未找到任何符合条件的文件!")
        sys.exit(1)

    return max(log_files, key=lambda x: int(x, 16))


def format_hex(value, length=8):
    # 将整数格式化为指定长度的十六进制字符串
    return f"0x{value:0{length}X}"


def calculate_next_log_id(max_number):
    # 计算日志文件的下一个编号
    return format_hex(int(max_number, 16) + 1, 24)


def calculate_next_transaction_id(max_number):
    # 计算下一个事务 ID，末尾补 00000
    next_id = (int(max_number, 16) + 1) * 0x100000
    return format_hex(next_id, 9)


def calculate_multixact_ids(max_hex, min_hex):
    # 计算下一个多事务 ID 和最旧的多事务 ID
    max_id = (int(max_hex, 16) + 1) * 0x10000
    min_id = (int(min_hex, 16) * 0x10000) + (1 if int(min_hex, 16) == 0 else 0)
    return format_hex(max_id, 8), format_hex(min_id, 8)


def calculate_members_offset(max_number):
    # 计算多事务成员的下一个编号和偏移量
    next_number = int(max_number, 16) + 1
    next_hex_number = format_hex(next_number, 8)
    next_offset = next_number * 0xCC80
    next_hex_offset = f"0x{next_offset:X}"
    return next_hex_number, next_hex_offset


def get_next_wal_start_position(kb_data):
    """
       1、确定新的 wal 最小的起始位置（-l 参数的值）
       - 查找 $KINGBASE_DATA/sys_wal 目录下的最大日志文件编号
       - 最大编号加 1 得到 wal 最小的起始位置
    """
    # 获取 WAL 目录路径
    wal_directory = os.path.join(kb_data, "sys_wal")
    max_number_wal = get_max_hex_number(wal_directory)
    next_hex_number_wal = f"{int(max_number_wal, 16) + 1:024X}"

    # 打印 WAL 结果
    wal_info = f"最大日志文件编号: {max_number_wal.zfill(24)}\n" \
        f"最大日志文件编号加 1 后的日志: {next_hex_number_wal}"

    print_log_info("WAL 信息", wal_info)

    return next_hex_number_wal


def get_next_transaction_id(kb_data):
    """
       2、确定下一个事务 id（-x 参数的值）
       - 查找 $KINGBASE_DATA/sys_xact 目录下的最大编号
       - 最大编号加 1，再在末尾补位 00000，得到下一个事务 id
    """
    # 获取 sys_xact 目录路径
    xact_directory = os.path.join(kb_data, "sys_xact")
    max_number_xact = get_max_hex_number(xact_directory)
    next_hex_id = calculate_next_transaction_id(max_number_xact)

    # 打印 sys_xact 结果
    transaction_info = (
        f"最大事务编号列: {max_number_xact}\n"
        f"最大事务编号加 1 末尾补 00000 后的事务 ID: {next_hex_id}"
    )

    print_log_info("XACT 事务信息", transaction_info)

    return next_hex_id


def get_multixact_ids(kb_data):
    """
        3、确定下一个多事务 ID 和最旧的多事务 ID（-m 参数的值）
        - 查找 $KINGBASE_DATA/sys_multixact/offsets 目录下的最大编号和最小编号
        - 最大编号加 1，再在末尾补位 0000，得到下一个多事务 ID
        - 最小编号在末尾补位 0000，得到下一个最旧的多事务 ID
        - 下一个最旧的多事务 ID 不能为 0，如果为 0 进行加 1 处理
    """
    # 获取 offsets 目录路径
    offsets_directory = os.path.join(kb_data, "sys_multixact", "offsets")
    max_number_offsets = get_max_hex_number(offsets_directory)

    # 查找符合十六进制格式的文件名
    log_files = [
        os.path.basename(f) for f in glob.glob(os.path.join(offsets_directory, "*"))
        if hex_pattern.match(os.path.basename(f))
    ]

    # 计算最小编号
    min_number_offsets = min(
        log_files, key=lambda x: int(x, 16)) if log_files else "0"

    # 计算 ID
    max_hex_result, min_hex_result = calculate_multixact_ids(
        max_number_offsets, min_number_offsets)

    # 打印 offsets 结果
    multixact_info = (
        f"最大多事务编号: {max_number_offsets}\n"
        f"最小多事务编号: {min_number_offsets}\n"
        f"下一个多事务 ID: {max_hex_result}\n"
        f"下一个最旧的多事务 ID: {min_hex_result}"
    )

    print_log_info("multixact 多事务信息", multixact_info)

    return max_hex_result, min_hex_result


def get_next_members_id(kb_data):
    """
       4、确定下一个多事务偏移量（-O 参数的值）
       - 查找 $KINGBASE_DATA/sys_multixact/members 目录下的最大编号
       - 最大编号加 1，然后乘以 0xCC80，得到下一个多事务偏移量
    """
    # 获取成员目录路径
    members_directory = os.path.join(kb_data, "sys_multixact", "members")

    # 获取最大编号
    max_number_members = get_max_hex_number(members_directory)

    # 计算下一个编号和下一个事务偏移量
    next_hex_number_members, next_hex_offset_members = calculate_members_offset(
        max_number_members)

    # 打印 members 结果
    members_info = (
        f"最大多事务成员编号: {max_number_members}\n"
        f"最大编号加 1 的编号: {next_hex_number_members}\n"
        f"下一个事务偏移量: {next_hex_offset_members}"
    )

    print_log_info("多事务成员信息", members_info)

    return next_hex_offset_members


def main():
    args = parse_arguments()
    compatible_style = args.compatible_style
    KINGBASE_DATA = args.kingbase_data if args.kingbase_data else os.getenv(
        "KINGBASE_DATA")

    if not KINGBASE_DATA:
        error_message("请设置 KINGBASE_DATA 环境变量或通过参数 [ -kd ] 传递!")
        sys.exit(1)

    # 控制文件路径
    control_file_path = os.path.join(KINGBASE_DATA, "global", "sys_control")

    # 检查控制文件是否存在
    if os.path.exists(control_file_path):
        error_message(f"控制文件 {control_file_path} 已存在，无需恢复，程序退出!")
        sys.exit(1)

    # 确定新的 WAL 最小的起始位置（-l 参数的值）
    minStartPosition = get_next_wal_start_position(KINGBASE_DATA)
    # 获取 sys_xact 目录的最大事务编号，并计算下一个事务 ID
    NextXID = get_next_transaction_id(KINGBASE_DATA)
    # 获取 sys_multixact/offsets 目录的最大和最小多事务编号，并计算下一个多事务 ID
    NextMultiXactId, oldestMultiXid = get_multixact_ids(KINGBASE_DATA)
    # 获取 sys_multixact/members 目录的最大多事务成员编号及其偏移量
    NextMultiOffset = get_next_members_id(KINGBASE_DATA)
    sys_resetwal_cmd = (
        f"sys_resetwal -f -l {minStartPosition} \\\n"
        f"    -x {NextXID} \\\n"
        f"    -m {NextMultiXactId},{oldestMultiXid} \\\n"
        f"    -O {NextMultiOffset} \\\n"
        f"    -D {KINGBASE_DATA} \\\n"
        f"    -g {compatible_style}"
    )
    print_log_info("生成 sys_resetwal 恢复命令", sys_resetwal_cmd)
    # 创建文件
    subprocess.run(
        ["touch", f"{KINGBASE_DATA}/global/sys_control"], check=True)
    # 列出文件信息
    control_file_info = subprocess.run(
        ["ls", "-l", f"{KINGBASE_DATA}/global/sys_control"], capture_output=True, check=True)
    print_log_info("创建一个空控制文件", control_file_info.stdout.strip())
    # 删除 kingbase.pid 文件
    pid_file_path = os.path.join(KINGBASE_DATA, "kingbase.pid")
    if os.path.exists(pid_file_path):
        print_log_info("正在删除 kingbase.pid 文件", pid_file_path)
        os.remove(pid_file_path)

    result = subprocess.run(sys_resetwal_cmd, shell=True,
                            capture_output=True, text=True)

    print_log_info("正在执行 sys_resetwal 恢复控制文件",
                   (result.stdout + result.stderr).strip())
    if result.returncode == 0:
        new_control_file_info = subprocess.run(
            ["ls", "-l", f"{KINGBASE_DATA}/global/sys_control"], capture_output=True, check=True)
        print_log_info("恢复的控制文件所在路径及大小如下",
                       new_control_file_info.stdout.strip())
        print("正在启动数据库：\n")
        os.system(f"sys_ctl start -D {KINGBASE_DATA}")
        print("\n恭喜！控制文件还原成功！！！\n")
    else:
        error_message("\n控制文件还原失败，请查找原因再次执行恢复！\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
