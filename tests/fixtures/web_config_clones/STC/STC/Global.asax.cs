// Trimmed copy of STC/Global.asax.cs. It keeps the Web.config lookups that the tests analyze.
using System;
using System.Configuration;
using System.Data;
using System.Data.SqlClient;

namespace STC
{
    public class Global : System.Web.HttpApplication
    {
        protected void Application_Error(object sender, EventArgs e)
        {
            Exception objErr = Server.GetLastError().GetBaseException();
            CommonFunction.SendMail("Error", objErr.Message, (String)ConfigurationManager.AppSettings["SysAdminMail"]);
            WriteDB(objErr.Message, Request.Url.ToString());
        }

        private void WriteDB(string str, string urlPath)
        {
            SqlConnection cn = new SqlConnection(ConfigurationManager.AppSettings["error"]);
            SqlCommand cmd = new SqlCommand("spAddRecordError", cn);
            cmd.CommandType = CommandType.StoredProcedure;
            cmd.Parameters.Add("@UrlPath", SqlDbType.VarChar, 500).Value = urlPath;
            cmd.Parameters.Add("@ErrorMessage", SqlDbType.Text).Value = str;
            cn.Open();
            cmd.ExecuteNonQuery();
            cn.Close();
        }
    }
}
