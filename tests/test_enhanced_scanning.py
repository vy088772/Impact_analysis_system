# test_enhanced_scanning.py
"""
測試增強版掃描功能
1. Service 層 SP 偵測
"""

def test_service_layer_detection():
    """測試 Service 層 SP 偵測"""
    print("=" * 80)
    print("測試 Service 層 SP 偵測")
    print("=" * 80)
    
    from code_analyzer.csharp_parser import CSharpParser
    
    # 測試代碼
    test_code = """
    using System;
    using Dapper;
    using System.Data.SqlClient;
    
    namespace MyApp.Services
    {
        public class UserService : IUserService
        {
            private readonly SqlConnection _connection;
            
            // Dapper 模式 1
            public async Task<User> GetUserAsync(int userId)
            {
                var result = await _connection.QueryFirstAsync<User>(
                    "spGetUserInfo", 
                    new { userId },
                    commandType: CommandType.StoredProcedure
                );
                return result;
            }
            
            // Dapper 模式 2
            public void UpdateUser(User user)
            {
                _connection.Execute("spUpdateUser", user, commandType: CommandType.StoredProcedure);
            }
            
            // Entity Framework
            public List<User> GetActiveUsers()
            {
                return _context.Users
                    .FromSqlRaw("EXEC spGetActiveUsers")
                    .ToList();
            }
        }
    }
    """
    
    # 寫入測試檔案
    test_file = "TestUserService.cs"
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write(test_code)
    
    # 解析
    parser = CSharpParser()
    result = parser.parse_file(test_file)
    
    print(f"\n找到 {len(result.stored_procedure_calls)} 個 SP 呼叫:")
    for sp in result.stored_procedure_calls:
        print(f"  - {sp.procedure_name} at line {sp.location.line_number}")
    
    # 清理
    import os
    os.remove(test_file)
    
    print("\n✅ 測試完成")


if __name__ == "__main__":
    # 測試 1: Service 層偵測
    test_service_layer_detection()
