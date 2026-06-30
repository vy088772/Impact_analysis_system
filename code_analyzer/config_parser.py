
import os
import re
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional

class WebConfigParser:
    """專案設定檔解析器 (支援 web.config 和 appsettings.json)"""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.connection_strings = {}
    
    def parse(self) -> Dict[str, str]:
        """
        解析設定檔中的連線字串
        優先順序: web.config -> appsettings.json
        Returns:
            Dict[Alias, ConnectionString]
        """
        # 1. 嘗試解析 web.config (Legacy .NET / MVC 5)
        web_config_path = self._find_file("web.config")
        if web_config_path:
            print(f"📖 讀取 web.config: {web_config_path}")
            self._parse_web_config(web_config_path)
            
        # 2. 嘗試解析 appsettings.json (.NET Core / Modern MVC)
        app_settings_path = self._find_file("appsettings.json")
        if app_settings_path:
            print(f"📖 讀取 appsettings.json: {app_settings_path}")
            self._parse_appsettings(app_settings_path)
            
        if not self.connection_strings:
            print("⚠️ 未找到任何資料庫連線設定 (web.config 或 appsettings.json)")

        return self.connection_strings
    
    def _parse_web_config(self, file_path: Path):
        """解析 web.config XML"""
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            
            for add in root.findall(".//connectionStrings/add"):
                name = add.get("name")
                conn_str = add.get("connectionString")
                
                if name and conn_str:
                    self.connection_strings[name] = conn_str
        except Exception as e:
            print(f"❌ 解析 web.config 失敗: {e}")

    def _parse_appsettings(self, file_path: Path):
        """解析 appsettings.json"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # 處理可能帶有註解的 JSON (簡單過濾)
                content = f.read()
                # 移除單行註解 //...
                content = re.sub(r'^\s*//.*$', '', content, flags=re.MULTILINE)
                
                data = json.loads(content)
                
                # 尋找 ConnectionStrings 區段
                conn_section = data.get("ConnectionStrings")
                if conn_section and isinstance(conn_section, dict):
                    for name, conn_str in conn_section.items():
                        if name and conn_str:
                            self.connection_strings[name] = conn_str
                            
        except json.JSONDecodeError as e:
            print(f"❌ 解析 appsettings.json 格式錯誤: {e}")
        except Exception as e:
            print(f"❌ 解析 appsettings.json 失敗: {e}")

    def _find_file(self, name_pattern: str) -> Optional[Path]:
        """遞迴/智慧尋找檔案"""
        # 1. 根目錄直接檢查
        full_path = self.project_root / name_pattern
        if full_path.exists():
            return full_path
            
        # 2. 根目錄 (不分大小寫)
        lower_pattern = name_pattern.lower()
        for file in os.listdir(self.project_root):
            if file.lower() == lower_pattern:
                return self.project_root / file

        # 3. 第一層子目錄 (通常是 MVC 專案的實際根目錄)
        for item in self.project_root.iterdir():
            if item.is_dir():
                possible = item / name_pattern
                if possible.exists():
                    return possible
                
                # Check case-insensitive inside subdir
                try:
                    for subfile in os.listdir(item):
                        if subfile.lower() == lower_pattern:
                            return item / subfile
                except:
                    continue
        
        return None

    def get_connection_info(self, connection_string: str) -> Dict[str, Optional[str]]:
        """
        從連線字串提取詳細資訊
        Returns:
            {
                'server': str,
                'database': str,
                'user_id': str,
                'password': str
            }
        """
        result = {
            'server': None,
            'database': None,
            'user_id': None,
            'password': None
        }
        
        # 提取 Server / Data Source
        server_patterns = [
            r'Data Source\s*=\s*([^;]+)',
            r'Server\s*=\s*([^;]+)',
            r'Address\s*=\s*([^;]+)',
            r'Addr\s*=\s*([^;]+)',
            r'Network Address\s*=\s*([^;]+)'
        ]
        
        for p in server_patterns:
            match = re.search(p, connection_string, re.IGNORECASE)
            if match:
                result['server'] = match.group(1).strip()
                break
                
        # 提取 Database / Initial Catalog
        db_patterns = [
            r'Initial Catalog\s*=\s*([^;]+)',
            r'Database\s*=\s*([^;]+)'
        ]
        
        for p in db_patterns:
            match = re.search(p, connection_string, re.IGNORECASE)
            if match:
                result['database'] = match.group(1).strip()
                break
                
        # 提取 User ID
        uid_patterns = [
            r'User ID\s*=\s*([^;]+)',
            r'UID\s*=\s*([^;]+)'
        ]
        
        for p in uid_patterns:
            match = re.search(p, connection_string, re.IGNORECASE)
            if match:
                result['user_id'] = match.group(1).strip()
                break
                
        # 提取 Password
        pwd_patterns = [
            r'Password\s*=\s*([^;]+)',
            r'PWD\s*=\s*([^;]+)'
        ]
        
        for p in pwd_patterns:
            match = re.search(p, connection_string, re.IGNORECASE)
            if match:
                result['password'] = match.group(1).strip()
                break
                
        return result
        
    def get_database_name(self, connection_string: str) -> Optional[str]:
        """從連線字串提取資料庫名稱（保留相容性）"""
        info = self.get_connection_info(connection_string)
        return info['database']
