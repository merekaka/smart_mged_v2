import os
import sys
import traceback
import re

try:
    import mysql.connector
except Exception as e:
    print("ERROR: 无法导入 mysql.connector — 请确认已安装 mysql-connector-python")
    print(e)
    sys.exit(2)

host = os.environ.get('MYSQL_HOST', '127.0.0.1')
port = int(os.environ.get('MYSQL_PORT', '3306'))
user = os.environ.get('MYSQL_USER', 'root')
password = os.environ.get('MYSQL_PASSWORD', 'CHANGE_ME_IN_PRODUCTION')
sql_path = os.path.join(os.getcwd(), 'smart_mged.sql')

print(f"尝试连接 MySQL -> {user}@{host}:{port}")

try:
    # 使用 pure-Python 实现以确保支持 multi 参数；如果数据库端/驱动不支持，后面有回退逻辑
    conn = mysql.connector.connect(host=host, port=port, user=user, password=password, use_pure=True)
except Exception as e:
    print("连接失败:")
    traceback.print_exc()
    sys.exit(1)

print("连接成功，开始执行 SQL 文件：", sql_path)

try:
    with open(sql_path, 'r', encoding='utf-8', errors='ignore') as f:
        sql = f.read()
except Exception as e:
    print("无法读取 SQL 文件:")
    traceback.print_exc()
    conn.close()
    sys.exit(1)

cursor = conn.cursor()

# 如果 SQL 文件中未指定数据库，尝试自动选择或创建一个数据库
db_from_env = os.environ.get('MYSQL_DATABASE')
db_from_sql = None
m = re.search(r"USE\s+`?([A-Za-z0-9_]+)`?;", sql, flags=re.IGNORECASE)
if m:
    db_from_sql = m.group(1)

target_db = db_from_env or db_from_sql or 'smart_mged'
try:
    print(f"确保数据库存在并切换到：{target_db}")
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{target_db}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci")
    cursor.execute(f"USE `{target_db}`")
except Exception:
    print('创建或切换数据库时发生错误，继续后续执行可能失败。')
    traceback.print_exc()

try:
    # 使用更可靠的分割函数按语义拆分 SQL（避免因为字符串中的换行或分号导致语句被错误切分）
    def split_sql_statements(text):
        stmts = []
        buf = []
        in_squote = in_dquote = in_bquote = False
        in_line_comment = False
        in_block_comment = False
        i = 0
        L = len(text)
        current_delim = ';'
        at_line_start = True

        def match_at(pos, token):
            return text[pos:pos+len(token)] == token

        while i < L:
            c = text[i]
            nc = text[i+1] if i+1 < L else ''

            # 行注释结束判断
            if in_line_comment:
                if c == '\n':
                    in_line_comment = False
                    buf.append(c)
                    at_line_start = True
                else:
                    buf.append(c)
                i += 1
                continue

            # 块注释处理
            if in_block_comment:
                if c == '*' and nc == '/':
                    buf.append('*/')
                    in_block_comment = False
                    i += 2
                else:
                    buf.append(c)
                    i += 1
                continue

            # 检测 DELIMITER 指令（只在行首有效且不在引号/注释中）
            if at_line_start and not in_squote and not in_dquote and not in_bquote:
                # 忽略前置空格
                j = i
                while j < L and text[j] in ' \t':
                    j += 1
                if text[j:j+9].lower() == 'delimiter':
                    # 找到 delimiter 指令，解析新的分隔符直到行尾
                    k = j+9
                    while k < L and text[k] in ' \t':
                        k += 1
                    # 读取分隔符 token 到换行
                    tstart = k
                    while k < L and text[k] not in '\r\n':
                        k += 1
                    newdel = text[tstart:k].strip()
                    if newdel:
                        current_delim = newdel
                        # 跳过到行尾
                        i = k
                        # consume newline(s)
                        while i < L and text[i] in '\r\n':
                            i += 1
                        at_line_start = True
                        continue
                    else:
                        # 没有指定 token，仍跳过该行
                        i = k
                        while i < L and text[i] in '\r\n':
                            i += 1
                        at_line_start = True
                        continue

            # 开始注释检测（非引号/反引号）
            if not in_squote and not in_dquote and not in_bquote:
                if c == '-' and nc == '-':
                    in_line_comment = True
                    buf.append('--')
                    i += 2
                    at_line_start = False
                    continue
                if c == '#':
                    in_line_comment = True
                    buf.append(c)
                    i += 1
                    at_line_start = False
                    continue
                if c == '/' and nc == '*':
                    in_block_comment = True
                    buf.append('/*')
                    i += 2
                    at_line_start = False
                    continue

            # 引号处理（考虑转义）
            if c == "'" and not in_dquote and not in_bquote:
                if not in_squote:
                    in_squote = True
                else:
                    back = 0
                    j = i-1
                    while j >= 0 and text[j] == '\\':
                        back += 1
                        j -= 1
                    if back % 2 == 0:
                        in_squote = False
                buf.append(c)
                i += 1
                at_line_start = False
                continue

            if c == '"' and not in_squote and not in_bquote:
                if not in_dquote:
                    in_dquote = True
                else:
                    back = 0
                    j = i-1
                    while j >= 0 and text[j] == '\\':
                        back += 1
                        j -= 1
                    if back % 2 == 0:
                        in_dquote = False
                buf.append(c)
                i += 1
                at_line_start = False
                continue

            if c == '`' and not in_squote and not in_dquote:
                in_bquote = not in_bquote
                buf.append(c)
                i += 1
                at_line_start = False
                continue

            # 检测当前分隔符（多字符也支持），仅在不在引号/注释中
            if not in_squote and not in_dquote and not in_bquote and not in_block_comment and not in_line_comment:
                if current_delim and match_at(i, current_delim):
                    stmt = ''.join(buf).strip()
                    if stmt:
                        stmts.append(stmt)
                    buf = []
                    i += len(current_delim)
                    # 跳过可能的换行
                    while i < L and text[i] in '\r\n':
                        i += 1
                    at_line_start = True
                    continue

            # 普通字符追加
            buf.append(c)
            at_line_start = (c == '\n')
            i += 1

        tail = ''.join(buf).strip()
        if tail:
            stmts.append(tail)
        return stmts

    statements = split_sql_statements(sql)
    print(f"解析出 {len(statements)} 条语句（将逐条执行）")
    for idx, stmt in enumerate(statements, start=1):
        short = stmt.replace('\n', ' ')[:200]
        print(f"[{idx}/{len(statements)}] 执行语句片段: {short}")
        try:
            cursor.execute(stmt)
            if cursor.with_rows:
                try:
                    rows = cursor.fetchall()
                    print(f"  返回行数: {len(rows)} (仅显示前 3 行)")
                    for r in rows[:3]:
                        print('   ', r)
                except Exception:
                    pass
        except Exception:
            print('执行该语句出错：', short)
            traceback.print_exc()
            raise
    conn.commit()
    print('SQL 分段执行完成并已提交。')
except Exception as e:
    print('执行 SQL 时发生错误:')
    traceback.print_exc()
    try:
        conn.rollback()
        print('已回滚。')
    except Exception:
        pass
    cursor.close()
    conn.close()
    sys.exit(1)


def upsert_abstract_summaries(db_conn, db_cursor):
    db_cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS abstract_summaries (
            abstract_id BIGINT PRIMARY KEY,
            abstract_content LONGTEXT NOT NULL,
            dataset_title VARCHAR(1024) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    abstracts_dir = os.path.join(project_root, 'data', 'abstracts')
    if not os.path.isdir(abstracts_dir):
        print(f"未找到摘要目录，跳过摘要入库：{abstracts_dir}")
        return

    filename_pattern = re.compile(r"^(?P<title>.+)_(?P<tid>\d+)_abstract\.md$", re.IGNORECASE)
    inserted = 0
    skipped = 0

    for file_name in sorted(os.listdir(abstracts_dir)):
        if not file_name.lower().endswith('.md'):
            continue

        match = filename_pattern.match(file_name)
        if not match:
            skipped += 1
            print(f"跳过不符合命名规则的摘要文件：{file_name}")
            continue

        abstract_id = int(match.group('tid'))
        dataset_title = match.group('title')
        file_path = os.path.join(abstracts_dir, file_name)

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                abstract_content = f.read().strip()
        except Exception:
            skipped += 1
            print(f"读取摘要文件失败，已跳过：{file_path}")
            traceback.print_exc()
            continue

        db_cursor.execute(
            """
            INSERT INTO abstract_summaries (abstract_id, abstract_content, dataset_title)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                abstract_content = VALUES(abstract_content),
                dataset_title = VALUES(dataset_title)
            """,
            (abstract_id, abstract_content, dataset_title)
        )
        inserted += 1

    db_conn.commit()
    print(f"摘要入库完成：成功写入/更新 {inserted} 条，跳过 {skipped} 条。")


def build_abstract_data_id_mapping(db_conn, db_cursor):
    db_cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS abstract_data_id_mapping (
            data_id BIGINT PRIMARY KEY,
            abstract_id BIGINT NOT NULL,
            title VARCHAR(1024) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_adm_abstract_id (abstract_id),
            KEY idx_adm_title (title(191)),
            CONSTRAINT fk_adm_abstract_id
                FOREIGN KEY (abstract_id)
                REFERENCES abstract_summaries(abstract_id)
                ON DELETE CASCADE
                ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )

    db_cursor.execute(
        """
        INSERT INTO abstract_data_id_mapping (data_id, abstract_id, title)
        SELECT e.data_id, a.abstract_id, e.title
        FROM entity_table e
        JOIN abstract_summaries a
                    ON e.title COLLATE utf8mb4_general_ci = a.dataset_title COLLATE utf8mb4_general_ci
        ON DUPLICATE KEY UPDATE
            abstract_id = VALUES(abstract_id),
            title = VALUES(title),
            updated_at = CURRENT_TIMESTAMP
        """
    )

    db_conn.commit()

    db_cursor.execute("SELECT COUNT(*) FROM abstract_data_id_mapping")
    mapped_total = db_cursor.fetchone()[0]
    db_cursor.execute(
        """
        SELECT COUNT(*)
        FROM entity_table e
        LEFT JOIN abstract_summaries a
                    ON e.title COLLATE utf8mb4_general_ci = a.dataset_title COLLATE utf8mb4_general_ci
        WHERE a.abstract_id IS NULL
        """
    )
    unmatched_total = db_cursor.fetchone()[0]
    print(f"映射表构建完成：当前映射 {mapped_total} 条，未匹配 title 的 entity 记录 {unmatched_total} 条。")


try:
    print('开始创建并填充摘要表 abstract_summaries ...')
    upsert_abstract_summaries(conn, cursor)
except Exception:
    print('摘要表处理失败：')
    traceback.print_exc()
    try:
        conn.rollback()
        print('摘要入库事务已回滚。')
    except Exception:
        pass
    cursor.close()
    conn.close()
    sys.exit(1)

try:
    print('开始创建并填充映射表 abstract_data_id_mapping ...')
    build_abstract_data_id_mapping(conn, cursor)
except Exception:
    print('映射表处理失败：')
    traceback.print_exc()
    try:
        conn.rollback()
        print('映射表事务已回滚。')
    except Exception:
        pass
    cursor.close()
    conn.close()
    sys.exit(1)

cursor.close()
conn.close()
print('全部完成，连接已关闭。')
sys.exit(0)
