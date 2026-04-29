"""
程序简介：处理飞书消息中的图片资源下载和本地缓存路径。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .im_api import FeishuIM

logger = logging.getLogger("feishu.assets")


def _guess_ext(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "png" in ct:
        return ".png"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "gif" in ct:
        return ".gif"
    if "webp" in ct:
        return ".webp"
    if "bmp" in ct:
        return ".bmp"
    return ".bin"


def _collect_image_keys(obj: Any, out: Set[str]) -> None:
    """
    递归遍历 parsed content，搜集所有 {"tag":"img","image_key":"..."} 的 image_key
    """
    if obj is None:
        return

    if isinstance(obj, dict):
        tag = obj.get("tag")
        if tag == "img" and obj.get("image_key"):
            out.add(str(obj["image_key"]))
        for v in obj.values():
            _collect_image_keys(v, out)
        return

    if isinstance(obj, list):
        for v in obj:
            _collect_image_keys(v, out)
        return


def download_image_from_message_resource(
    im: FeishuIM,
    message_id: str,
    image_key: str,
    images_dir: Path,
    *,
    skip_existing: bool = True,
) -> Dict[str, Any]:
    """
    兜底方案：从“消息资源”接口下载图片
    GET /im/v1/messages/{message_id}/resources/{file_key}?type=image
    通常 file_key 可以直接用 image_key 传。
    """
    images_dir.mkdir(parents=True, exist_ok=True)

    if skip_existing:
        for ext in (".png", ".jpg", ".gif", ".webp", ".bmp", ".bin"):
            p = images_dir / f"{image_key}{ext}"
            if p.exists():
                return {
                    "ok": True,
                    "method": "message_resource",
                    "image_key": image_key,
                    "path": str(p),
                    "content_type": None,
                    "skipped": True,
                }

    url = f"{im.client.base_url}/im/v1/messages/{message_id}/resources/{image_key}"
    headers = im._auth_headers()
    params = {"type": "image"}

    try:
        resp = im.client.session.get(url, headers=headers, params=params, timeout=30)
    except Exception as e:
        return {"ok": False, "method": "message_resource", "image_key": image_key, "error": f"request_error: {e}"}

    if resp.status_code != 200:
        err_msg = f"http_{resp.status_code}"
        try:
            j = resp.json()
            err_msg = f"http_{resp.status_code} code={j.get('code')} msg={j.get('msg')}"
        except Exception:
            pass
        return {"ok": False, "method": "message_resource", "image_key": image_key, "error": err_msg}

    content_type = resp.headers.get("Content-Type", "") or ""
    ext = _guess_ext(content_type)
    out_path = images_dir / f"{image_key}{ext}"

    try:
        out_path.write_bytes(resp.content)
    except Exception as e:
        return {"ok": False, "method": "message_resource", "image_key": image_key, "error": f"write_error: {e}"}

    return {
        "ok": True,
        "method": "message_resource",
        "image_key": image_key,
        "path": str(out_path),
        "content_type": content_type,
        "skipped": False,
    }


def download_image_by_key(
    im: FeishuIM,
    image_key: str,
    images_dir: Path,
    *,
    message_id: Optional[str] = None,
    skip_existing: bool = True,
    image_type: str = "message",
) -> Dict[str, Any]:
    """
    先走 /im/v1/images/{image_key}（仅应用自有资源能下）
    若返回 234008（非资源发送方），且提供了 message_id，则兜底走“消息资源下载”。
    """
    images_dir.mkdir(parents=True, exist_ok=True)

    if skip_existing:
        for ext in (".png", ".jpg", ".gif", ".webp", ".bmp", ".bin"):
            p = images_dir / f"{image_key}{ext}"
            if p.exists():
                return {
                    "ok": True,
                    "method": "image_get",
                    "image_key": image_key,
                    "path": str(p),
                    "content_type": None,
                    "skipped": True,
                }

    # 1) 优先：下载图片资源（仅应用自己上传的可成功）
    url = f"{im.client.base_url}/im/v1/images/{image_key}"
    headers = im._auth_headers()
    params = {"type": image_type}

    try:
        resp = im.client.session.get(url, headers=headers, params=params, timeout=30)
    except Exception as e:
        return {"ok": False, "method": "image_get", "image_key": image_key, "error": f"request_error: {e}"}

    if resp.status_code != 200:
        code = None
        msg = None
        try:
            j = resp.json()
            code = j.get("code")
            msg = j.get("msg")
        except Exception:
            pass

        # 2) 兜底：234008 说明不是资源发送方，改走消息资源下载
        if code == 234008 and message_id:
            return download_image_from_message_resource(
                im,
                message_id,
                image_key,
                images_dir,
                skip_existing=skip_existing,
            )

        err_msg = f"http_{resp.status_code}"
        if code is not None:
            err_msg = f"http_{resp.status_code} code={code} msg={msg}"
        return {"ok": False, "method": "image_get", "image_key": image_key, "error": err_msg}

    content_type = resp.headers.get("Content-Type", "") or ""
    ext = _guess_ext(content_type)
    out_path = images_dir / f"{image_key}{ext}"

    try:
        out_path.write_bytes(resp.content)
    except Exception as e:
        return {"ok": False, "method": "image_get", "image_key": image_key, "error": f"write_error: {e}"}

    return {
        "ok": True,
        "method": "image_get",
        "image_key": image_key,
        "path": str(out_path),
        "content_type": content_type,
        "skipped": False,
    }


def enrich_message_with_local_images(
    message: Dict[str, Any],
    im: FeishuIM,
    *,
    data_dir: Path,
    enable: bool = True,
    skip_existing: bool = True,
) -> Dict[str, Any]:
    """
    从 message["content"]["parsed"] 里找 image_key，下载到 data/images，并把本地路径写回 message。
    写入字段：
      message["local_assets"]["images"] = [{image_key, ok, path, error, method, ...}, ...]
    """
    if not enable:
        return message

    parsed = (message.get("content") or {}).get("parsed")
    keys: Set[str] = set()
    _collect_image_keys(parsed, keys)
    if not keys:
        return message

    images_dir = data_dir / "images"
    msg_id = str(message.get("message_id") or "") or None

    results: List[Dict[str, Any]] = []
    for k in sorted(keys):
        r = download_image_by_key(
            im,
            k,
            images_dir,
            message_id=msg_id,
            skip_existing=skip_existing,
            image_type="message",
        )
        results.append(r)

    la = message.setdefault("local_assets", {})
    la["images"] = results
    return message

