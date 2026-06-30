# config/sp_detector_config.py
"""
預存程序偵測設定管理
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
import re


class SPDetectionConfig:
    """預存程序偵測設定"""
    
    DEFAULT_CONFIG = {
        "wrapper_methods": [
            "ExeProcRead",
            "CreateReader",
            "CreateDataSet",
            "CreateTable"
        ],
        "sp_name_patterns": [
            "^sp[A-Z_]",
            "^SP[A-Z_]"
        ],
        "detect_command_type": True,
        "detect_exec_statements": True,
        "require_sp_prefix": False,
        "min_proc_name_length": 3
    }
    
    def __init__(self, config_file: Optional[str] = None):
        """
        初始化設定
        
        Args:
            config_file: 設定檔路徑，如果為 None 則使用預設路徑
        """
        if config_file is None:
            # 預設路徑：config/sp_detection_rules.json
            base_dir = Path(__file__).parent
            config_file = base_dir / "sp_detection_rules.json"
        
        self.config_file = Path(config_file)
        self.config = self._load_config()
        self._compile_patterns()
    
    def _load_config(self) -> Dict:
        """載入設定檔"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                print(f"✅ 已載入預存程序偵測設定: {self.config_file}")
                
                # 合併預設設定（確保所有必要欄位都存在）
                config = self.DEFAULT_CONFIG.copy()
                config.update(loaded_config)
                return config
            except Exception as e:
                print(f"⚠️ 載入設定檔失敗: {e}，使用預設設定")
                return self.DEFAULT_CONFIG.copy()
        else:
            print(f"⚠️ 設定檔不存在: {self.config_file}，使用預設設定")
            # 建立預設設定檔
            self._create_default_config()
            return self.DEFAULT_CONFIG.copy()
    
    def _create_default_config(self):
        """建立預設設定檔"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            default_config_with_comments = {
                "wrapper_methods": self.DEFAULT_CONFIG["wrapper_methods"],
                "sp_name_patterns": self.DEFAULT_CONFIG["sp_name_patterns"],
                "detect_command_type": self.DEFAULT_CONFIG["detect_command_type"],
                "detect_exec_statements": self.DEFAULT_CONFIG["detect_exec_statements"],
                "require_sp_prefix": self.DEFAULT_CONFIG["require_sp_prefix"],
                "min_proc_name_length": self.DEFAULT_CONFIG["min_proc_name_length"],
                "comments": {
                    "wrapper_methods": "自訂的預存程序封裝方法名稱",
                    "sp_name_patterns": "預存程序命名模式（正規表達式）",
                    "detect_command_type": "是否偵測 SqlCommand with CommandType.StoredProcedure",
                    "detect_exec_statements": "是否偵測直接 EXEC/EXECUTE 語句",
                    "require_sp_prefix": "是否要求預存程序名稱必須有前綴",
                    "min_proc_name_length": "預存程序名稱最小長度"
                }
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config_with_comments, f, indent=2, ensure_ascii=False)
            
            print(f"✅ 已建立預設設定檔: {self.config_file}")
        except Exception as e:
            print(f"❌ 建立預設設定檔失敗: {e}")
    
    def _compile_patterns(self):
        """編譯正規表達式模式"""
        self.compiled_patterns = []
        for pattern in self.sp_name_patterns:
            try:
                self.compiled_patterns.append(re.compile(pattern))
            except re.error as e:
                print(f"⚠️ 無效的正規表達式模式: {pattern}, 錯誤: {e}")
    
    @property
    def wrapper_methods(self) -> List[str]:
        """取得封裝方法清單"""
        return self.config.get("wrapper_methods", [])
    
    @property
    def sp_name_patterns(self) -> List[str]:
        """取得預存程序命名模式"""
        return self.config.get("sp_name_patterns", [])
    
    @property
    def detect_command_type(self) -> bool:
        """是否偵測 SqlCommand"""
        return self.config.get("detect_command_type", True)
    
    @property
    def detect_exec_statements(self) -> bool:
        """是否偵測 EXEC 語句"""
        return self.config.get("detect_exec_statements", True)
    
    @property
    def require_sp_prefix(self) -> bool:
        """是否要求預存程序名稱有前綴"""
        return self.config.get("require_sp_prefix", False)
    
    @property
    def min_proc_name_length(self) -> int:
        """預存程序名稱最小長度"""
        return self.config.get("min_proc_name_length", 3)
    
    def is_valid_sp_name(self, proc_name: str) -> bool:
        """
        驗證預存程序名稱是否符合規則
        
        Args:
            proc_name: 預存程序名稱
            
        Returns:
            bool: 是否為有效的預存程序名稱
        """
        # 檢查長度
        if len(proc_name) < self.min_proc_name_length:
            return False
        
        # 如果要求前綴，檢查是否匹配任何模式
        if self.require_sp_prefix:
            if not self.compiled_patterns:
                return False
            
            for pattern in self.compiled_patterns:
                if pattern.match(proc_name):
                    return True
            return False
        
        # 不要求前綴，檢查是否匹配任何模式（作為提示）
        # 或者直接接受
        if self.compiled_patterns:
            for pattern in self.compiled_patterns:
                if pattern.match(proc_name):
                    return True
        
        # 如果沒有模式或不匹配，也接受（寬鬆模式）
        return True
    
    def add_wrapper_method(self, method_name: str):
        """新增封裝方法"""
        if method_name not in self.wrapper_methods:
            self.config["wrapper_methods"].append(method_name)
    
    def remove_wrapper_method(self, method_name: str):
        """移除封裝方法"""
        if method_name in self.config["wrapper_methods"]:
            self.config["wrapper_methods"].remove(method_name)
    
    def save_config(self):
        """儲存設定到檔案"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 移除 comments 欄位（如果存在）
            save_config = {k: v for k, v in self.config.items() if k != "comments"}
            
            # 加入註解
            save_config["comments"] = {
                "wrapper_methods": "自訂的預存程序封裝方法名稱",
                "sp_name_patterns": "預存程序命名模式（正規表達式）",
                "detect_command_type": "是否偵測 SqlCommand with CommandType.StoredProcedure",
                "detect_exec_statements": "是否偵測直接 EXEC/EXECUTE 語句",
                "require_sp_prefix": "是否要求預存程序名稱必須有前綴",
                "min_proc_name_length": "預存程序名稱最小長度"
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(save_config, f, indent=2, ensure_ascii=False)
            
            print(f"✅ 設定已儲存: {self.config_file}")
            return True
        except Exception as e:
            print(f"❌ 儲存設定失敗: {e}")
            return False
    
    def print_config(self):
        """顯示目前設定"""
        print("=" * 60)
        print("預存程序偵測設定")
        print("=" * 60)
        print(f"設定檔: {self.config_file}")
        print(f"\n封裝方法 ({len(self.wrapper_methods)}):")
        for method in self.wrapper_methods:
            print(f"  - {method}")
        print(f"\n命名模式 ({len(self.sp_name_patterns)}):")
        for pattern in self.sp_name_patterns:
            print(f"  - {pattern}")
        print(f"\n選項:")
        print(f"  偵測 SqlCommand: {self.detect_command_type}")
        print(f"  偵測 EXEC 語句: {self.detect_exec_statements}")
        print(f"  要求前綴: {self.require_sp_prefix}")
        print(f"  最小長度: {self.min_proc_name_length}")
        print("=" * 60)


# ============================================
# 測試程式碼
# ============================================

if __name__ == "__main__":
    # 測試設定載入
    config = SPDetectionConfig()
    config.print_config()
    
    # 測試名稱驗證
    print("\n測試預存程序名稱驗證:")
    test_names = [
        "spAddNewCompany",
        "spGetUserList",
        "SP_DeleteUser",
        "procUpdateStatus",
        "GetData",  # 不符合模式
        "sp",       # 太短
    ]
    
    for name in test_names:
        valid = config.is_valid_sp_name(name)
        status = "✅" if valid else "❌"
        print(f"  {status} {name}")
    
    # 測試新增方法
    print("\n測試新增封裝方法:")
    config.add_wrapper_method("CustomExecuteProc")
    print(f"  新增後的方法清單: {config.wrapper_methods}")
    
    # 測試儲存
    print("\n測試儲存設定:")
    config.save_config()