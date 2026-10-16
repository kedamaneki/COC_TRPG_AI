using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

internal static class AquesTalkBridge
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr LoadLibrary(string path);
    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
    private static extern IntPtr GetProcAddress(IntPtr module, string name);
    [DllImport("kernel32.dll")]
    private static extern bool FreeLibrary(IntPtr module);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate IntPtr SyntheDelegate(byte[] text, int speed, out int size);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void FreeWaveDelegate(IntPtr wave);

    public static int Main(string[] args)
    {
        if (args.Length != 4) return 2;
        IntPtr module = LoadLibrary(Path.GetFullPath(args[0]));
        if (module == IntPtr.Zero) return 3;
        try
        {
            IntPtr synthPtr = GetProcAddress(module, "AquesTalk_Synthe");
            IntPtr freePtr = GetProcAddress(module, "AquesTalk_FreeWave");
            if (synthPtr == IntPtr.Zero || freePtr == IntPtr.Zero) return 4;
            var synth = (SyntheDelegate)Marshal.GetDelegateForFunctionPointer(synthPtr, typeof(SyntheDelegate));
            var free = (FreeWaveDelegate)Marshal.GetDelegateForFunctionPointer(freePtr, typeof(FreeWaveDelegate));
            byte[] body = Encoding.GetEncoding(932).GetBytes(args[2]);
            byte[] text = new byte[body.Length + 1];
            Buffer.BlockCopy(body, 0, text, 0, body.Length);
            int size;
            IntPtr wave = synth(text, Int32.Parse(args[1]), out size);
            if (wave == IntPtr.Zero) { Console.Error.WriteLine(size); return 5; }
            try
            {
                byte[] bytes = new byte[size];
                Marshal.Copy(wave, bytes, 0, size);
                File.WriteAllBytes(args[3], bytes);
            }
            finally { free(wave); }
            return 0;
        }
        finally { FreeLibrary(module); }
    }
}
