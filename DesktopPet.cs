// DesktopPet.cs —— 独立 Win11 桌面桌宠（WPF 版）
// 解决：per-pixel alpha 完美透明（透明 PNG 无紫边）、RenderTransform 精确复刻插件按压动画、点按播音。
// 兼容：Windows .NET Framework 4.0+（Win10/11 自带 .NET Framework + WPF），C# 5 语法，零外部依赖。
// 资源：exe 同目录 assets\characters\<角色>\image.png + 语音 mp3。
//
// 点按逻辑（复刻 dsh-pet）：
//   - 按下：RenderTransform = ScaleX(1.05) ScaleY(0.88)（压扁，带弹性过渡）
//   - 松开：回弹到 Scale(1,1)
//   - 播音：星绘按时间 morning/noon/evening；白墨固定 sprint
using System;
using System.IO;
using System.Media;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;

namespace DshDesktopPet
{
    public class App : Application
    {
        [STAThread]
        public static void Main(string[] args)
        {
            App app = new App();
            PetWindow w = new PetWindow();
            app.MainWindow = w;
            w.Show();
            app.Run();
        }
    }

    public class PetWindow : Window
    {
        private const string DEFAULT_ROLE = "星绘";
        private const double BaseSize = 200.0;

        private System.Windows.Controls.Image image;
        private string currentRole = DEFAULT_ROLE;
        private SoundPlayer player = new SoundPlayer();

        private Point downPoint;
        private bool isDown = false;
        private bool movedAsDrag = false;
        private Point dragOffset;

        public PetWindow()
        {
            // 无边框、置顶、透明背景（per-pixel alpha，解决紫边）
            this.WindowStyle = WindowStyle.None;
            this.ResizeMode = ResizeMode.NoResize;
            this.Topmost = true;
            this.ShowInTaskbar = false;
            this.AllowsTransparency = true;
            this.Background = Brushes.Transparent;
            this.SizeToContent = SizeToContent.WidthAndHeight;
            this.Cursor = Cursors.Hand;

            image = new System.Windows.Controls.Image();
            image.Width = BaseSize;
            image.Height = BaseSize;
            RenderOptions.SetBitmapScalingMode(image, System.Windows.Media.BitmapScalingMode.NearestNeighbor);
            this.Content = image;

            // 右键菜单：切换角色 / 退出
            var menu = new System.Windows.Controls.ContextMenu();
            var miSwitch = new System.Windows.Controls.MenuItem();
            miSwitch.Header = "切换角色";
            miSwitch.Click += delegate { CycleRole(); };
            var miExit = new System.Windows.Controls.MenuItem();
            miExit.Header = "退出";
            miExit.Click += delegate { Close(); };
            menu.Items.Add(miSwitch);
            menu.Items.Add(miExit);
            image.ContextMenu = menu;

            LoadRole(DEFAULT_ROLE);
            PlaceDefault();
        }

        private void PlaceDefault()
        {
            var wa = System.Windows.SystemParameters.WorkArea;
            this.Left = wa.Right - this.Width - 24;
            this.Top = wa.Bottom - this.Height - 24;
        }

        private void LoadRole(string role)
        {
            currentRole = role;
            string dir = Path.Combine(GetBaseDir(), "assets", "characters", role);
            string imgPath = Path.Combine(dir, "image.png");
            try
            {
                if (File.Exists(imgPath))
                {
                    var bmp = new System.Windows.Media.Imaging.BitmapImage();
                    bmp.BeginInit();
                    bmp.UriSource = new Uri(imgPath, UriKind.Absolute);
                    bmp.CacheOption = System.Windows.Media.Imaging.BitmapCacheOption.OnLoad;
                    bmp.EndInit();
                    image.Source = bmp;
                }
            }
            catch { }
        }

        private void CycleRole()
        {
            string next = (currentRole == "星绘") ? "白墨" : "星绘";
            LoadRole(next);
        }

        // ---- 播音（复刻插件：星绘按时间，白墨固定冲刺）----
        private void PlayClickVoice()
        {
            string dir = Path.Combine(GetBaseDir(), "assets", "characters", currentRole);
            string file = null;
            if (currentRole == "白墨")
            {
                file = Path.Combine(dir, "sprint.mp3");
            }
            else if (currentRole == "星绘")
            {
                file = Path.Combine(dir, GreetingForNow() + ".mp3");
            }
            else
            {
                string click = Path.Combine(dir, "click.mp3");
                file = File.Exists(click) ? click : Path.Combine(dir, "morning.mp3");
            }
            try
            {
                if (File.Exists(file))
                {
                    player.Stop();
                    player.SoundLocation = file;
                    player.Load();
                    player.Play();
                }
            }
            catch { }
        }

        private static string GreetingForNow()
        {
            int h = DateTime.Now.Hour;
            if (h >= 6 && h < 12) return "morning";
            if (h >= 12 && h < 18) return "noon";
            return "evening";
        }

        // ---- 按压动画（复刻插件 SQUISH = scaleY(0.88) scaleX(1.05)，弹性回弹）----
        private void ApplyScale(double sx, double sy, double ms, bool bounce)
        {
            // 用 RenderTransform 做缩放：插件是 CSS transform scaleY(0.88) scaleX(1.05)
            var st = new ScaleTransform(sx, sy);
            var translate = new TranslateTransform();
            var group = new TransformGroup();
            group.Children.Add(st);
            group.Children.Add(translate);
            image.RenderTransform = group;
            image.RenderTransformOrigin = new Point(0.5, 0.5);

            // 弹性缓动：回弹用 cubic-bezier(.34,1.56,.64,1) 的近似（过冲弹性）
            System.Windows.Media.Animation.EasingFunctionBase ease;
            if (bounce)
                ease = new System.Windows.Media.Animation.QuinticEase { EasingMode = EasingMode.EaseOut };
            else
                ease = new System.Windows.Media.Animation.QuadraticEase { EasingMode = EasingMode.EaseOut };
            var animX = new DoubleAnimation(sx, 1.0, TimeSpan.FromMilliseconds(ms)) { EasingFunction = ease };
            var animY = new DoubleAnimation(sy, 1.0, TimeSpan.FromMilliseconds(ms)) { EasingFunction = ease };
            st.BeginAnimation(ScaleTransform.ScaleXProperty, animX);
            st.BeginAnimation(ScaleTransform.ScaleYProperty, animY);
        }

        // ---- 鼠标事件 ----
        protected override void OnMouseLeftButtonDown(MouseButtonEventArgs e)
        {
            base.OnMouseLeftButtonDown(e);
            isDown = true;
            movedAsDrag = false;
            downPoint = e.GetPosition(this);
            dragOffset = e.GetPosition(this);
            // 按下瞬间压扁（插件 SQUISH）
            ApplyScale(1.05, 0.88, 90, false);
            image.Focus();
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);
            if (isDown && e.LeftButton == MouseButtonState.Pressed)
            {
                Point cur = e.GetPosition(this);
                if (Math.Abs(cur.X - downPoint.X) > 6 || Math.Abs(cur.Y - downPoint.Y) > 6)
                {
                    movedAsDrag = true;
                    // 拖动：移动窗口
                    Point screen = PointToScreen(e.GetPosition(this));
                    this.Left = screen.X - dragOffset.X;
                    this.Top = screen.Y - dragOffset.Y;
                }
            }
        }

        protected override void OnMouseLeftButtonUp(MouseButtonEventArgs e)
        {
            base.OnMouseLeftButtonUp(e);
            isDown = false;
            // 松开回弹到 1.0（弹性）
            ApplyScale(1.0, 1.0, 260, true);
            // 未拖动 = 点击 → 播音
            if (!movedAsDrag)
            {
                PlayClickVoice();
            }
        }

        private static string GetBaseDir()
        {
            return AppDomain.CurrentDomain.BaseDirectory;
        }

        protected override void OnClosed(EventArgs e)
        {
            try { player.Stop(); } catch { }
            base.OnClosed(e);
        }
    }
}
