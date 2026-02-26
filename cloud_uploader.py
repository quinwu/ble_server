#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import logging
import time
import json
from pathlib import Path
from typing import Optional, Dict
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class CloudUploader:
    """云端上传器 - 负责图片上传和重试"""
    
    def __init__(self, upload_url: str = "", timeout: int = 30):
        self.upload_url = upload_url
        self.timeout = timeout
        
        # 请求会话（复用连接）
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'BLE-Device-Uploader/1.0'
        })
    
    def set_upload_url(self, url: str) -> bool:
        """设置上传 URL"""
        try:
            # 验证 URL 格式
            result = urlparse(url)
            if not all([result.scheme, result.netloc]):
                logger.error(f"无效的 URL: {url}")
                return False
            
            self.upload_url = url
            logger.info(f"上传 URL 已设置: {url}")
            return True
            
        except Exception as e:
            logger.error(f"设置上传 URL 异常: {e}")
            return False
    
    def upload(
        self,
        metadata: Dict,
        authorization: str = "",
        retry_times: int = 3,
        retry_delay: int = 2
    ) -> bool:
        """
        上传数据到云端（标准 POST 请求）
        
        Args:
            metadata: 包含所有上传数据的字典，必须包含 file_data（base64编码的文件数据）
            authorization: Authorization header 值（可选）
            retry_times: 重试次数
            retry_delay: 重试延迟（秒）
            
        Returns:
            bool: 上传是否成功
        """
        if not self.upload_url:
            logger.error("上传 URL 未配置")
            return False
        
        if not metadata:
            logger.error("metadata 不能为空")
            return False
        
        file_name = metadata.get("file_name", "unknown.jpg")
        logger.info(f"开始上传: {file_name} -> {self.upload_url}")
        
        for attempt in range(retry_times):
            try:
                # 设置请求头
                headers = {
                    'Content-Type': 'application/json',
                    'User-Agent': 'BLE-Device-Uploader/1.0'
                }
                
                # 如果提供了 authorization，添加到 headers
                if authorization:
                    headers['Authorization'] = authorization
                
                # 发送标准 POST 请求，metadata 作为 JSON body
                response = self.session.post(
                    self.upload_url,
                    json=metadata,
                    headers=headers,
                    timeout=self.timeout
                )
                
                # 检查响应
                if response.status_code == 200:
                    logger.info(f"上传成功: {file_name}")
                    logger.debug(f"响应内容: {response.text[:200]}")
                    return True
                else:
                    logger.warning(
                        f"上传失败（状态码 {response.status_code}，"
                        f"尝试 {attempt + 1}/{retry_times}）: {response.text[:200]}"
                    )
                        
            except requests.exceptions.Timeout:
                logger.warning(f"上传超时（尝试 {attempt + 1}/{retry_times}）")
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"连接错误（尝试 {attempt + 1}/{retry_times}）: {e}")
            except Exception as e:
                logger.error(f"上传异常: {e}", exc_info=True)
            
            # 重试延迟
            if attempt < retry_times - 1:
                logger.info(f"等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
        
        logger.error(f"上传失败，已重试 {retry_times} 次")
        return False
    
    def upload_multipart(
        self,
        filepath: str,
        chunk_size: int = 1024 * 1024,  # 1MB
        retry_times: int = 3
    ) -> bool:
        """
        分片上传（适用于大文件）
        
        Args:
            filepath: 文件路径
            chunk_size: 分片大小（字节）
            retry_times: 重试次数
            
        Returns:
            bool: 上传是否成功
        """
        # 这里提供一个简化的分片上传实现
        # 实际使用时需要根据服务端 API 进行调整
        
        file_path = Path(filepath)
        if not file_path.exists():
            logger.error(f"文件不存在: {filepath}")
            return False
        
        file_size = file_path.stat().st_size
        total_chunks = (file_size + chunk_size - 1) // chunk_size
        
        logger.info(f"开始分片上传: {filepath}，共 {total_chunks} 片")
        
        try:
            with open(file_path, 'rb') as f:
                for chunk_index in range(total_chunks):
                    chunk_data = f.read(chunk_size)
                    
                    # 上传分片
                    success = self._upload_chunk(
                        chunk_data,
                        chunk_index,
                        total_chunks,
                        file_path.name,
                        retry_times
                    )
                    
                    if not success:
                        logger.error(f"分片 {chunk_index + 1}/{total_chunks} 上传失败")
                        return False
                    
                    logger.info(f"分片 {chunk_index + 1}/{total_chunks} 上传成功")
            
            logger.info("分片上传完成")
            return True
            
        except Exception as e:
            logger.error(f"分片上传异常: {e}", exc_info=True)
            return False
    
    def _upload_chunk(
        self,
        chunk_data: bytes,
        chunk_index: int,
        total_chunks: int,
        filename: str,
        retry_times: int
    ) -> bool:
        """上传单个分片"""
        for attempt in range(retry_times):
            try:
                response = self.session.post(
                    self.upload_url,
                    data={
                        'chunk_index': chunk_index,
                        'total_chunks': total_chunks,
                        'filename': filename
                    },
                    files={'chunk': chunk_data},
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    return True
                else:
                    logger.warning(f"分片上传失败（尝试 {attempt + 1}/{retry_times}）")
                    
            except Exception as e:
                logger.warning(f"分片上传异常（尝试 {attempt + 1}/{retry_times}）: {e}")
            
            time.sleep(1)
        
        return False
    
    def test_connection(self) -> bool:
        """测试与服务器的连接"""
        if not self.upload_url:
            logger.error("上传 URL 未配置")
            return False
        
        try:
            # 发送 HEAD 请求测试连接
            response = self.session.head(
                self.upload_url,
                timeout=10
            )
            
            logger.info(f"服务器连接测试成功（状态码 {response.status_code}）")
            return True
            
        except Exception as e:
            logger.error(f"服务器连接测试失败: {e}")
            return False


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    uploader = CloudUploader()
    
    # 设置上传 URL
    uploader.set_upload_url("https://httpbin.org/post")
    
    # 测试连接
    if uploader.test_connection():
        print("服务器连接正常")
    
    # 创建测试文件并转换为 base64
    test_file = Path("/tmp/test_image.jpg")
    test_file.write_bytes(b"fake image data for testing")
    
    import base64
    with open(test_file, 'rb') as f:
        file_data = base64.b64encode(f.read()).decode('utf-8')
    
    # 测试上传（使用新的格式）
    metadata = {
        "file_name": "test_image.jpg",
        "file_area": 1,
        "file_batch": "test_batch",
        "device_id": "test-001",
        "camera_device": "/dev/video0",
        "file_data": file_data
    }
    
    if uploader.upload(metadata):
        print("上传成功")
    else:
        print("上传失败")
    
    # 清理
    test_file.unlink(missing_ok=True)
