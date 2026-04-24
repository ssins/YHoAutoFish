import time

class PIDController:
    def __init__(self, kp, ki, kd, output_limits=(None, None)):
        self.kp = kp  # 比例系数：反应当前的差距
        self.ki = ki  # 积分系数：消除长期静态误差
        self.kd = kd  # 微分系数：预测未来趋势，防止过冲（刹车）
        
        self.output_limits = output_limits
        self.reset()

    def reset(self):
        self.integral = 0
        self.last_error = 0
        self.last_time = time.time()

    def update(self, error):
        now = time.time()
        dt = now - self.last_time
        
        # 第一次调用或时间极短，不计算 I 和 D
        if dt <= 0.001: 
            return self.kp * error
            
        # 1. 比例项 (P)
        p_out = self.kp * error
        
        # 2. 积分项 (I) - 增加抗饱和 (Anti-windup) 处理
        self.integral += error * dt
        # 限制积分范围，防止长时间偏离导致积分值爆炸（这里将积分限制在比较小的范围）
        self.integral = max(min(self.integral, 20), -20) 
        i_out = self.ki * self.integral
        
        # 3. 微分项 (D) - 关键：计算游标靠近速度，提前减速
        derivative = (error - self.last_error) / dt
        d_out = self.kd * derivative
        
        output = p_out + i_out + d_out
        
        # 更新状态
        self.last_error = error
        self.last_time = now
        
        # 限制输出范围
        min_limit, max_limit = self.output_limits
        if min_limit is not None:
            output = max(output, min_limit)
        if max_limit is not None:
            output = min(output, max_limit)
            
        return output
