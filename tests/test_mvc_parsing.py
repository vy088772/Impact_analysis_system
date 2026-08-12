"""
測試 MVC 專案的 SP 偵測
"""
from code_analyzer.csharp_parser import CSharpParser

def test_mvc_service():
    """測試 MVC Service 檔案的 SP 偵測"""
    
    # 測試檔案路徑
    test_file = r"d:\TOPCSCY\Andy\TOPCSCY\Services\ORD\OrdFileSpecMtnService.cs"
    
    print("=" * 80)
    print("測試 MVC 專案的 SP 偵測")
    print("=" * 80)
    print(f"\n檔案: {test_file}")
    
    # 建立解析器
    parser = CSharpParser()
    
    # 解析檔案
    result = parser.parse_file(test_file)
    
    # 輸出結果
    print(f"\n✅ 解析完成")
    print(f"\n類別數量: {len(result.classes)}")
    
    if result.classes:
        for cls in result.classes:
            print(f"\n類別: {cls.name}")
            print(f"  方法數量: {len(cls.methods)}")
    
    print(f"\n找到的 SP 呼叫: {len(result.stored_procedure_calls)}")
    
    if result.stored_procedure_calls:
        print("\nSP 清單:")
        for sp_call in result.stored_procedure_calls:
            print(f"  ✅ {sp_call.procedure_name}")
            print(f"      行號: {sp_call.location.line_number}")
            print(f"      資料庫: {sp_call.database_source or 'unknown'}")
            print(f"      連線變數: {sp_call.connection_variable or 'N/A'}")
    else:
        print("\n❌ 沒有找到任何 SP 呼叫！")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    test_mvc_service()
