/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2022 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "i2c.h"
#include "usart.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "stdio.h"
#include "lsm6dsox_read_data_polling.h"
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */
#define I2C_REQUEST_WRITE                       0x00
#define I2C_REQUEST_READ                        0x01

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */
char msg_uart[2000];
int size_uart_tx = 0;
int elapsed_time = 0;

/* Print function */
void print_uart(char *msg, int size_tx)
{
	for (int inx_pck = 0; inx_pck < size_tx; inx_pck++)
	{
	  while(!(USART2->SR & USART_SR_TXE));
    LL_USART_TransmitData8(USART2, msg[inx_pck]);
	}
  while(!(USART2->SR & USART_SR_TC));
}

/* I2C write function */
void i2c_write(uint8_t dev_addr, uint8_t reg, uint8_t *data, int tx_size)
{
	/* Prepare CAK for Master data RX */
	//LL_I2C_AcknowledgeNextData(I2C1, LL_I2C_ACK);

	/* Master generates Start condition */
	LL_I2C_GenerateStartCondition(I2C1);

	while(!LL_I2C_IsActiveFlag_SB(I2C1));

	/* Send Slave address with a 7-Bit SLAVE_OWN_ADDRESS for a write request */
	LL_I2C_TransmitData8(I2C1, (uint8_t)(dev_addr<<1)| I2C_REQUEST_WRITE);

	/* Address of the device */
	while(!LL_I2C_IsActiveFlag_ADDR(I2C1));

	LL_I2C_ClearFlag_ADDR(I2C1);

	/* TX the register */
	LL_I2C_TransmitData8(I2C1, reg);

	/* Wait until the TX register is emptied */
	while(!LL_I2C_IsActiveFlag_TXE(I2C1));

	/* Send the data */
	for(int inx_tx = 0; inx_tx<tx_size; inx_tx++)
	{
		LL_I2C_TransmitData8(I2C1, data[inx_tx]);

		while(!LL_I2C_IsActiveFlag_TXE(I2C1));

	}

	/* Master generates Stop condition */
	LL_I2C_GenerateStopCondition(I2C1);

	while(LL_I2C_IsActiveFlag_BUSY(I2C1));

}

/* I2C read function */
void i2c_read(uint8_t dev_addr, uint8_t reg, uint8_t *data_received, int rx_size)
{
	/*Starting the tx part to ping the sensor */
	/* Master generates Start condition */
	LL_I2C_GenerateStartCondition(I2C1);

	/* Wait for the start bit to show up */
	while(!LL_I2C_IsActiveFlag_SB(I2C1));

	/* Send Slave address with a 7-Bit SLAVE_OWN_ADDRESS for a write request */
	LL_I2C_TransmitData8(I2C1, (uint8_t)(dev_addr<<1)| I2C_REQUEST_WRITE);

	/* Wait until the ADDR is acknowledged */
	while(!LL_I2C_IsActiveFlag_ADDR(I2C1));

	/* Clear ADDR flag value in ISR register */
	LL_I2C_ClearFlag_ADDR(I2C1);

	/* Send the register to be read */
	LL_I2C_TransmitData8(I2C1, (uint8_t)reg);

	/* Wait for the tx to finish */
	while(!LL_I2C_IsActiveFlag_TXE(I2C1));

	/*Starting the read part! */
	/* Master generates Start condition */
	LL_I2C_GenerateStartCondition(I2C1);

	/* Wait for the start bit to show up */
	while(!LL_I2C_IsActiveFlag_SB(I2C1));

	/* Send Slave address with a 7-Bit SLAVE_OWN_ADDRESS for a write request */
	LL_I2C_TransmitData8(I2C1, (uint8_t)(dev_addr<<1)| I2C_REQUEST_READ);

	/* Wait until the ADDR is acknowledged */
	while(!LL_I2C_IsActiveFlag_ADDR(I2C1));

	/* Clear ADDR flag value in ISR register */
	LL_I2C_ClearFlag_ADDR(I2C1);

	for(int inx_data = 0; inx_data<rx_size; inx_data++)
	{
		/* Set the (N)ACK depending on the state. NACK will terminate the transmission */
		if(inx_data<(rx_size-1))
			LL_I2C_AcknowledgeNextData(I2C1, LL_I2C_ACK);
		else
			LL_I2C_AcknowledgeNextData(I2C1, LL_I2C_NACK);

		/* Wait until the data arrives */
		while(!LL_I2C_IsActiveFlag_RXNE(I2C1));

		/* Store the data */
		data_received[inx_data] = LL_I2C_ReceiveData8(I2C1);
	}

	/* Master generates Stop condition */
	LL_I2C_GenerateStopCondition(I2C1);

	/* Make sure all is completed */
	while(LL_I2C_IsActiveFlag_BUSY(I2C1));

}

/* Delay function, remember to tick the variable @elapsed_time on the Systick! */
void delay_ms(int ms)
{
	elapsed_time = 0;
	while(elapsed_time<ms);
}
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */


/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_I2C1_Init();
  MX_USART2_UART_Init();
  /* USER CODE BEGIN 2 */
  LL_USART_EnableIT_RXNE(USART2);
  LL_USART_Enable(USART2);
  LL_I2C_Enable(I2C1);
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {

	  lsm6dsox_read_data_polling();

    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */

  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE2);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = 8;
  RCC_OscInitStruct.PLL.PLLN = 84;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 4;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
