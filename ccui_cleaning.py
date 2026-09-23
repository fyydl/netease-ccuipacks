import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed


def get_valid_path(prompt, is_file=False):
    """交互式获取并规范化路径（去除拖拽带来的双引号）"""
    while True:
        path = input(prompt).strip().strip('"').strip("'")
        if not path:
            return ""
        if is_file:
            if os.path.isfile(path):
                return path
            print(f"[错误] 找不到指定的程序文件: {path}，请重新输入。")
        else:
            if os.path.isdir(path):
                return path
            print(f"[错误] 找不到指定的文件夹: {path}，请重新输入。")


def process_single_file(ffmpeg_path, input_file, rel_path, dest_dir, vf_filter):
    """单文件处理函数，由线程池并发调用"""
    out_file_final = os.path.join(dest_dir, rel_path)
    out_folder = os.path.dirname(out_file_final)
    
    # 自动创建深层输出目录（多线程下加锁防竞争）
    os.makedirs(out_folder, exist_ok=True)

    temp_png = out_file_final + ".png"

    # FFmpeg 命令参数
    cmd = [
        ffmpeg_path,
        "-loglevel", "error",
        "-i", input_file,
        "-vf", vf_filter,
        "-compression_level", "9",
        "-y",
        temp_png,
    ]

    try:
        subprocess.run(cmd, check=True)

        # 压缩成功后重命名/移动回 .1 后缀
        if os.path.exists(temp_png):
            if os.path.exists(out_file_final):
                os.remove(out_file_final)
            shutil.move(temp_png, out_file_final)
        return True, rel_path
    except Exception as e:
        if os.path.exists(temp_png):
            os.remove(temp_png)
        return False, f"{rel_path} ({e})"


def clean_2_files(directory):
    """统计并批量删除指定目录下的 .2 文件（需用户确认）"""
    files_to_delete = []
    total_size = 0

    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith(".2"):
                file_path = os.path.join(root, f)
                try:
                    size = os.path.getsize(file_path)
                    files_to_delete.append(file_path)
                    total_size += size
                except OSError as e:
                    print(f"[警告] 无法获取文件大小 {file_path}: {e}")

    if not files_to_delete:
        print("未在目标文件夹中找到任何 .2 文件。")
        return

    def format_size(size_bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"

    print(f"\n检测到 {len(files_to_delete)} 个 .2 文件。")
    print(f"总大小: {total_size} 字节 ({format_size(total_size)})")

    confirm = input("\n是否确认删除这些 .2 文件？(y/n): ").strip().lower()
    if confirm == 'y':
        deleted_count = 0
        for file_path in files_to_delete:
            try:
                os.remove(file_path)
                deleted_count += 1
            except OSError as e:
                print(f"[错误] 删除失败 {file_path}: {e}")
        print(f"成功删除 {deleted_count} 个 .2 文件。\n")
    else:
        print("已取消删除 .2 文件操作。\n")


def main():
    print("=" * 60)
    print(" FFmpeg PNG (.1) 递归批量压缩及文件清理同步工具")
    print("=" * 60 + "\n")

    # 1. 获取 ffmpeg 路径
    ffmpeg_path = input(
        "请输入或拖入 ffmpeg.exe 的完整路径（如果已配置环境变量可直接回车）: "
    ).strip().strip('"').strip("'")
    if not ffmpeg_path:
        ffmpeg_path = "ffmpeg"

    try:
        subprocess.run(
            [ffmpeg_path, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except Exception:
        print(f"\n[错误] 无法运行 FFmpeg: '{ffmpeg_path}'。请确保路径正确或已配置环境变量。")
        sys.exit(1)

    # 2. 获取目标与输出文件夹路径
    print()
    src_dir = get_valid_path("请输入或拖入【目标文件夹】路径: ", is_file=False)
    dest_dir = input("请输入或拖入【输出文件夹】路径: ").strip().strip('"').strip("'")

    if not dest_dir:
        print("[错误] 输出文件夹路径不能为空！")
        sys.exit(1)

    # 附加逻辑：询问并清理目标文件夹中的 .2 文件
    clean_choice = input("\n是否需要扫描并清理目标文件夹中的 .2 文件？(y/n): ").strip().lower()
    if clean_choice == 'y':
        clean_2_files(src_dir)

    # 3. 动态配置并发线程数
    default_workers = os.cpu_count() or 4
    workers_input = input(f"请输入并发线程数 [默认推荐 {default_workers}]: ").strip()
    try:
        max_workers = int(workers_input) if workers_input else default_workers
    except ValueError:
        max_workers = default_workers

    print("\n" + "=" * 60)
    print(f"FFmpeg 路径 : {ffmpeg_path}")
    print(f"目标文件夹  : {src_dir}")
    print(f"输出文件夹  : {dest_dir}")
    print(f"并发线程数  : {max_workers}")
    print("=" * 60 + "\n")

    # 滤镜参数定义
    vf_filter = "split[s0][s1];[s0]palettegen=max_colors=256:reserve_transparent=on[p];[s1][p]paletteuse=dither=sierra2_4a"

    # 4. 扫描收集所有待处理的 .1 文件以及其他不需要压缩的文件
    compress_tasks = []
    other_files = []

    for root, _, files in os.walk(src_dir):
        for file in files:
            input_file = os.path.join(root, file)
            rel_path = os.path.relpath(input_file, src_dir)
            if file.lower().endswith(".1"):
                compress_tasks.append((input_file, rel_path))
            else:
                other_files.append((input_file, rel_path))

    # 先同步复制其他未处理的文件至输出文件夹
    if other_files:
        print(f"正在复制 {len(other_files)} 个其他文件（非 .1 文件）至输出文件夹...")
        for input_file, rel_path in other_files:
            dest_file = os.path.join(dest_dir, rel_path)
            os.makedirs(os.path.dirname(dest_file), exist_ok=True)
            shutil.copy2(input_file, dest_file)
        print("其他文件同步复制完成！\n")

    total_files = len(compress_tasks)
    print(f"共扫描到 {total_files} 个 .1 待处理文件，开始并行压缩...\n")

    completed_count = 0
    success_count = 0

    # 5. 多线程并发执行压缩任务
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {
            executor.submit(
                process_single_file, ffmpeg_path, input_file, rel_path, dest_dir, vf_filter
            ): rel_path
            for input_file, rel_path in compress_tasks
        }

        for future in as_completed(future_to_task):
            completed_count += 1
            success, msg = future.result()
            
            if success:
                success_count += 1
                print(f"[{completed_count}/{total_files}] 完成: {msg}")
            else:
                print(f"[{completed_count}/{total_files}] 失败: {msg}")

    print("\n" + "=" * 60)
    print(f"全量处理完成！压缩成功: {success_count}/{total_files} 个 .1 文件")
    print(f"其他文件已同步复制: {len(other_files)} 个")
    print(f"完整结果已存入目录: {dest_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()